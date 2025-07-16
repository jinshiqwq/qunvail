# /opt/AstrBot/data/plugins/qunvail/main.py
import asyncio
import aiohttp

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

VERIFY_URL = "http://qun.2b2t.biz/vailed.php"
TARGET_GROUPS = {"713498179", "978088976"}   # 仅这两个群生效


@register("qunvail", "Soulter", "进群验证插件（硬编码群）", "1.0.0")
class QunVail(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.pending = set()          # 正在验证的 QQ
        logger.info("[qunvail] 插件已加载，目标群：713498179、978088976")

    # 1. 监听群成员增加
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_event(self, event: AstrMessageEvent):
        raw = event.message_obj.raw_message
        if raw.get("post_type") != "notice" or raw.get("notice_type") != "group_increase":
            return

        gid = str(raw["group_id"])
        uid = str(raw["user_id"])
        if gid not in TARGET_GROUPS:
            return

        logger.info(f"[qunvail] 群 {gid} 新成员 {uid}，开始验证")
        self.pending.add(uid)
        asyncio.create_task(self._verify_and_kick(event, gid, uid))

    # 2. 未验证成员消息直接撤回
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_msg(self, event: AstrMessageEvent):
        gid = str(event.group_id)
        uid = str(event.get_sender_id())
        if gid in TARGET_GROUPS and uid in self.pending:
            try:
                await event.recall()
            except Exception as e:
                logger.warning(f"[qunvail] 撤回失败: {e}")

    async def _verify_and_kick(self, event: AstrMessageEvent, gid: str, uid: str):
        adapter = event.platform_adapter
        for _ in range(30):          # 30×10s ≈ 5 分钟
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
                    params = {"qq": uid, "qun": gid}
                    async with s.get(VERIFY_URL, params=params) as r:
                        if (await r.text()).strip().lower() == "yes":
                            logger.info(f"[qunvail] {uid} 验证通过")
                            self.pending.discard(uid)
                            return
            except Exception as e:
                logger.error(f"[qunvail] 验证接口异常: {e}")
            await asyncio.sleep(10)

        # 超时踢人
        logger.info(f"[qunvail] {uid} 验证超时，踢出群 {gid}")
        self.pending.discard(uid)
        try:
            await adapter.kick_group_member(gid, uid)
        except Exception as e:
            logger.error(f"[qunvail] 踢人失败: {e}")

    async def terminate(self):
        logger.info("[qunvail] 插件已卸载")
