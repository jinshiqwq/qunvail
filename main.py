# qun_verify.py
import asyncio
import aiohttp
from typing import List, Dict, Set

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, GroupMemberIncreaseEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain, Reply
from astrbot.api.platform import PlatformAdapter

VERIFY_URL = "http://qun.2b2t.biz/vailed.php"


@register(
    "qun_verify",
    "Soulter",
    "进群验证插件：未在 http://qun.2b2t.biz 验证的成员 5 分钟内踢出",
    "1.0.0",
)
class QunVerifyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.cfg: Dict = context.get_config()
        # 需要验证的群号列表
        self.target_groups: List[str] = self.cfg.get("qun_verify_groups", [])
        # 正在验证中的 qq -> 任务
        self.pending: Set[str] = set()

    async def initialize(self):
        logger.info(f"[qun_verify] 已加载，目标群：{self.target_groups}")

    # 群成员增加事件
    @filter.event(GroupMemberIncreaseEvent)
    async def on_member_increase(self, event: GroupMemberIncreaseEvent):
        group_id = str(event.group_id)
        user_id = str(event.user_id)

        if group_id not in self.target_groups:
            return

        logger.info(f"[qun_verify] 群 {group_id} 有新成员 {user_id}，开始验证流程")
        self.pending.add(user_id)

        # 启动验证协程
        asyncio.create_task(self._verify_and_kick(event, group_id, user_id))

    # 普通消息事件：未验证成员的消息直接撤回
    @filter.event_type("message")
    async def on_message(self, event: AstrMessageEvent):
        if event.message_type != "group":
            return
        user_id = str(event.get_sender_id())
        group_id = str(event.group_id)

        if group_id not in self.target_groups:
            return
        if user_id not in self.pending:
            return

        # 撤回
        try:
            await event.recall()
            logger.debug(f"[qun_verify] 撤回 {user_id} 在群 {group_id} 的消息")
        except Exception as e:
            logger.warning(f"[qun_verify] 撤回消息失败: {e}")

    async def _verify_and_kick(self, event: GroupMemberIncreaseEvent, group_id: str, user_id: str):
        """轮询验证接口，最多 5 分钟"""
        adapter: PlatformAdapter = event.platform_adapter
        max_retry = 30  # 10s * 30 = 5min
        for _ in range(max_retry):
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                    params = {"qq": user_id, "qun": group_id}
                    async with session.get(VERIFY_URL, params=params) as resp:
                        text = (await resp.text()).strip()
                        if text == "yes":
                            logger.info(f"[qun_verify] {user_id} 已验证通过")
                            self.pending.discard(user_id)
                            return
                        elif text == "no":
                            pass  # 继续等待
                        else:
                            logger.warning(f"[qun_verify] 接口返回异常: {text}")
            except Exception as e:
                logger.error(f"[qun_verify] 请求验证接口失败: {e}")
            await asyncio.sleep(10)

        # 超时未验证
        logger.info(f"[qun_verify] {user_id} 验证超时，踢出群 {group_id}")
        self.pending.discard(user_id)
        try:
            await adapter.kick_group_member(group_id, user_id)
        except Exception as e:
            logger.error(f"[qun_verify] 踢人失败: {e}")

    async def terminate(self):
        logger.info("[qun_verify] 插件已卸载")
