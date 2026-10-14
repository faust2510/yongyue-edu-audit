from . import api
from . import chat
from . import person
from . import send_log
from . import update_log  # B3 幂等去重（bot.handle_update 用它）
from . import bot
# —— 功能模块（集成者统一挂，顺序有讲究）——
from . import template   # F6 文案模板（reminder 依赖它，必须在前）
from . import reminder   # F1 定时提醒
from . import dm         # F2 一对一私发
from . import notify     # F3 广播
from . import mention    # F5 @提醒
from . import poll       # F4 打卡（F1 定时提醒带按钮时用；与 reply 的 ck: 分流）
from . import reply      # F4 按钮回填
from . import selfcheck  # D1 自检页（瞬态，后台「自检」菜单）
from . import llm        # F7 大模型客户端（默认零出网，配齐参数才发）
from . import notion     # F7 Notion 客户端（默认关，保底 title+正文）
from . import material   # F7 材料归档（老师私聊转发 → 规则/LLM 抽取 → 可选导出）
from . import bindcode   # 身份绑定码（/bind 深链 + /bindcode 签发；2026-10-12 用户裁定）
from . import forward  # 选项 c：后台「材料归档 → 📤 转发给…」（文件走 file_id，不重传）
from . import menu       # 按钮化界面（2026-10-13 用户反馈：不想记斜杠指令，点按钮就行）
from . import bridge     # 对接选项 b：站内通知桥（edu.message → Telegram；2026-10-14）
