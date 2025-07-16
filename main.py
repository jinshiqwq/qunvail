# main.py
import asyncio
import aiohttp
from typing import Set, List

from astrbot.api.event import filter, AstrMessageEvent, GroupMemberIncreaseEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain
from astrbot.api.platform import PlatformAdapter

VERIFY_URL = "http://qun.2b2t.biz/vailed.php"


@register(
    "astrbot_plugin_qun_verify",
    "Soulter",
    "进群验证：未验证的成员 5 分钟内踢出",
    "1.0.0",
)
class QunVerifyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        cfg = context.get_config()
        # 支持在 AstrBot 管理面板里配置群号
        self.target_groups: List[str] = cfg.get("qun_verify_groups", [])
        self.pending: Set[str] = set()  # 正在验证的 qq
        logger.info(f"[qun_verify] 已加载，目标群：{self.target_groups}")

    # 群成员增加事件
    @filter.event(GroupMemberIncreaseEvent)
    async def on_member_increase(self, event: GroupMemberIncreaseEvent):
        gid = str(event.group_id)
        uid = str(event.user_id)
        if gid not in self.target_groups:
            return

        logger.info(f"[qun_verify] 群 {gid} 有新成员 {uid}，开始验证")
        self.pending.add(uid)
        asyncio.create_task(self._verify_and_kick(event, gid, uid))

    # 普通消息：未验证成员的消息直接撤回
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

    async def _verify_and_kick(self, event: GroupMemberIncreaseEvent, gid: str, uid: str):
        adapter: PlatformAdapter = event.platform_adapter
        max_retry = 30  # 10s * 30 = 5min
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
                        elif text == "no":
                            pass
                        else:
                            logger.warning(f"[qun_verify] 接口返回异常: {text}")
                except Exception as e:
                    logger.error(f"[qun_verify] 请求验证接口失败: {e}")
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
