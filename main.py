import asyncio
import aiohttp
from typing import Set, List

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain

VERIFY_URL = "http://qun.2b2t.biz/vailed.php"


@register(
    "astrbot_plugin_qun_verify",
    "Soulter",
    "进群验证：未在 http://qun.2b2t.biz 验证的成员 5 分钟内踢出",
    "1.0.0",
)
class QunVerifyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        cfg = context.get_config()
        self.target_groups: List[str] = [str(g) for g in cfg.get("qun_verify_groups", [])]
        self.pending: Set[str] = set()
        logger.info(f"[qun_verify] 已加载，目标群：{self.target_groups}")

    # 1. 监听群成员增加事件
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_event(self, event: AstrMessageEvent):
        # 只处理 notice 类型里的 group_member_increase
        if event.message_obj.type.value != "notice":
            return
        raw = event.message_obj.raw_message
        if raw.get("notice_type") != "group_increase":
            return

        gid = str(raw["group_id"])
        uid = str(raw["user_id"])
        if gid not in self.target_groups:
            return

        logger.info(f"[qun_verify] 群 {gid} 有新成员 {uid}，开始验证")
        self.pending.add(uid)
        asyncio.create_task(self._verify_and_kick(event, gid, uid))

    # 2. 未验证成员的消息直接撤回
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_msg(self, event: AstrMessageEvent):
        gid = str(event.group_id)
        uid = str(event.get_sender_id())
        if gid not in self.target_groups or uid not in self.pending:
            return
        try:
            await event.recall()
            logger.debug(f"[qun_verify] 撤回 {uid} 在群 {gid} 的消息")
        except Exception as e:
            logger.warning(f"[qun_verify] 撤回失败: {e}")

    async def _verify_and_kick(self, event: AstrMessageEvent, gid: str, uid: str):
        adapter = event.platform_adapter
        max_retry = 30
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as sess:
            for _ in range(max_retry):
                try:
                    params = {"qq": uid, "qun": gid}
                    async with sess.get(VERIFY_URL, params=params) as resp:
                        text = (await resp.text()).strip().lower()
                        if text == "yes":
                            logger.info(f"[qun_verify] {uid} 验证通过")
                            self.pending.discard(uid)
                            return
                except Exception as e:
                    logger.error(f"[qun_verify] 验证接口异常: {e}")
                await asyncio.sleep(10)

        # 超时踢人
        logger.info(f"[qun_verify] {uid} 验证超时，踢出群 {gid}")
        self.pending.discard(uid)
        try:
            await adapter.kick_group_member(gid, uid)
        except Exception as e:
            logger.error(f"[qun_verify] 踢人失败: {e}")

    async def terminate(self):
        logger.info("[qun_verify] 插件已卸载")
