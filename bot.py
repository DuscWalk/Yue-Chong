from __future__ import annotations

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from qq_rolebot.config import load_settings


def main() -> None:
    settings = load_settings()
    nonebot.init(
        driver="~fastapi",
        host=settings.host,
        port=settings.port,
        onebot_access_token=settings.onebot_access_token,
    )
    driver = nonebot.get_driver()
    driver.register_adapter(OneBotV11Adapter)
    nonebot.load_plugin("qq_rolebot.plugins.roleplay_chat")
    nonebot.run()


if __name__ == "__main__":
    main()
