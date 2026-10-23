# 羊羊狩猎者

《羊了个羊：星球》微信小游戏的 Windows 桌面通关辅助。程序读取关卡地图、计算路线，在游戏窗口上标出下一张牌；可由玩家手动点击，也可开启自动点击普通牌。目前只辅助第二关，第一关由玩家自行完成。

项目在一局 225 张牌的第二关上完成过真实通关。那局使用了一次“移出”和一次“复活”；求解器支持这两种道具，以及从移出区取回卡牌。规划时先尝试普通路线，再从已到达的深层局面使用道具，并尝试不同的开局、选牌顺序和道具时机。后续关卡是否能找到路线仍取决于地图和搜索预算，程序不会把超时当作“无解”。

当前本机捕获的一局 216 张牌难局已通过完整路线搜索和规则引擎重放验证，测试机器约 10 秒求解，回归地图在 `tests/fixtures/difficult_216.json`。自动规划会先找普通选牌路线，再从其深入位置尝试道具，同时保留不同开局的搜索；30 秒时给出提示并继续搜索，单轮预算约 120 秒。若仍未找到，可点击“重新规划”或重新开一局。道具“洗牌”会改变全图牌型分布，目前未纳入自动规划。

对于含变色牌的特殊地图，可在监听新局前勾选“特殊关卡：三消后重新计算变色牌”。程序根据地图中的变色牌标记和本局种子复现游戏的洗牌规则，每次比较多组可行三消，优先消除仍压着深层牌的厚区卡牌，并检查下一次变色后的可接续性；三消后更新牌型再规划。特殊模式开启自动点击后，重算期间暂停点击，得到下一段路线后自动继续；遇到“移出”或“复活”仍会关闭自动点击，需手动使用道具并重新开启。该模式仍是逐段搜索，当前不能保证找到整局通关路线；变色牌的牌面预测依赖游戏客户端的规则和随机数消耗顺序。普通模式保持原有完整路线搜索。

## 准备环境

- Windows 和电脑版微信，能打开《羊了个羊：星球》小游戏。
- Python 3.7+；运行 `python -m pip install -r requirements.txt` 安装 Pillow。
- Node.js，用于按种子还原牌面。
- mitmproxy 的 `mitmdump.exe`。当前脚本按 `C:\Program Files\mitmproxy\bin\mitmdump.exe` 查找；安装在别处时修改 [start_capture.ps1](scripts/start_capture.ps1) 中的路径。首次使用需运行一次 `mitmdump` 生成证书。
- 抓包脚本默认通过 `http://127.0.0.1:12000` 上游代理转发。没有该代理时，需要按本机网络环境调整 [start_capture.ps1](scripts/start_capture.ps1) 的 `UpstreamProxy` 或抓包模式。

## 使用

Windows 上直接双击项目根目录的 `羊羊狩猎者.exe`。它使用同目录下的 `scripts/`、`yangyang_hunter/templates/`，并将本机抓取数据保存在 `captures/`。请保留这些目录；exe 已包含运行界面所需的 Python 环境，但监听新局仍需要上面列出的 Node.js 和 mitmproxy。

也可以在项目目录从 Python 源码运行：

```powershell
pythonw -m yangyang_hunter
```

需要重新生成 exe 时，使用 Python 3.8 或更新版本先安装打包工具，然后执行：

```powershell
py -3.8 -m pip install pyinstaller Pillow
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

生成文件位于项目根目录的 `羊羊狩猎者.exe`；`build/` 是可忽略的临时打包文件。

在辅助界面点击“监听下一局”，然后进入小游戏。程序获取本局种子后，会在本地恢复牌面并搜索路线。第一关不会显示提示；进入第二关后，红圈标出建议点击的牌。保持“自动识别我在游戏中的点击”勾选即可按提示手动点击。

搜索当前关卡时也可以直接点“监听下一局”：旧搜索会立即取消，旧路线不会再写回界面，自动点击会关闭，程序开始监听新的开局。

勾选“自动点击棋盘和移出区牌（道具手动）”后，程序会在游戏窗口处于前台时自动点击已规划的棋盘牌和移出区卡牌。路线走到“移出”或“复活”时会自动取消勾选；你手动完成道具后，再自行勾选才能继续自动点击。复活后还需点“确认这步已完成”。移出区会优先使用道具动画识别到的位置；识别失败时按游戏的固定三列位置点击。每次自动点击前后都会核对游戏槽位张数，目标牌没有明显变化、槽位与模型不一致或复活用尽后下一步会填满槽位时立即暂停。取消勾选可随时停止自动点击。

自动点击的尝试、确认和槽位不一致事件会记录在本机 `captures/auto_click_trace.jsonl`，便于复盘；此文件不会上传到仓库。

遇到新的第二关地图时，程序会继续等待该局的 `.map` 抓包，自动解码并保存在本机；如果游戏直接使用缓存、抓包里没有地图，则根据本局地图编号从游戏静态资源地址下载。已经出现“新关卡准备失败”时，重启新版界面后点“重新规划”，可直接使用 `captures/` 中最近一次的种子和地图重试，无需重新开局。地图恢复成功不保证搜索预算内一定找到路线；未找到时界面会明确提示。

路线要求使用道具时，界面会显示“移出”或“复活”。“移出”后会定位移出区的三列牌，并跟踪在该区域的点击；“复活”目前需要在游戏中操作后点击“确认这步已完成”。如果某次点击没有同步，可用“确认这步已完成”“撤销识别”或下拉框“补记这张牌”修正。

从已有的本地地图和路线继续时，可传入 `--map`、`--tool-solution` 和 `--resume`。`--resume` 是已经完成的**操作数**，包括道具操作。运行时关卡文件和路线保存在本机的 `captures/`，不会上传；仓库仅包含去除抓包元数据的测试地图。

## 工作原理

1. [capture_map.py](yangyang_hunter/capture_map.py) 和 [seed_probe.py](yangyang_hunter/seed_probe.py) 通过 mitmproxy 获取关卡地图与本局种子。只保存需要的响应数据，并过滤常见身份字段。
2. [map_templates.py](yangyang_hunter/map_templates.py) 查找或获取本局地图，[decode_map.py](yangyang_hunter/decode_map.py) 解析地图；[restore_types.js](scripts/restore_types.js) 依据种子还原每张牌的图案及变色牌开局洗牌。[special_rules.py](yangyang_hunter/special_rules.py) 在三消后继续重放变色规则。`yangyang_hunter/templates/` 放有已知地图结构模板，不含用户凭据；新地图只保存在本机 `captures/`。
3. [board_model.py](yangyang_hunter/board_model.py)、[solve.py](yangyang_hunter/solve.py) 和 [solve_with_tools.py](yangyang_hunter/solve_with_tools.py) 建模遮挡、七格槽和道具，搜索并重放验证路线。
4. [desktop_assistant.py](yangyang_hunter/desktop_assistant.py) 显示下一步，监听玩家的点击；开启自动模式后也可点击普通牌。每步检查画面变化，再推进或重新规划。

`captures/`、`.env`、证书和本机代理状态均不纳入版本控制。程序依赖当前版本的微信窗口标题、画面布局、种子格式和游戏规则；这些内容更新后可能需要重新校准。

详细设计见 [DESIGN.md](docs/DESIGN.md)。运行 `python -m unittest discover -s tests -q` 可检查基础规则模型。
