# 四家运营商资费站 · 本次开发说明

基于 [amxysw/carrier-tariff-site](https://github.com/amxysw/carrier-tariff-site) 的 MIT 许可源码扩展，保留原作者 LICENSE 与四个运营商页面。此项目为第三方公开资费展示站，不是运营商官网。

## 已实现

- 保留移动、电信、联通、广电的全国资费与原站查询、分类、历史、收藏功能。
- 四个原站新增“我的资费”入口，对应 `/custom/`。
- 默认地区：江苏电信、江苏移动、江苏联通、江苏广电、上海移动、上海电信、上海联通、浙江电信、河北联通、河南联通、四川联通、广东联通；默认附带四家全国资费。
- 个性化页面支持地区组合、关键词、名称搜索、运营商、类型、明确月费区间、排序、收藏、最多四条比较、全量筛选结果 CSV 导出。
- 支持本机自定义资费的新增、修改、删除；个人配置、收藏与自定义记录可以 JSON 导入导出。导入成功会替换当前配置。
- 深浅色与移动端布局；来源与快照时间可见；未接入省份显示缺失和官方链接，不伪造零条或借用全国数据。
- 覆盖清单 `data/coverage.json` 由真实文件生成，枚举四家运营商 × 全国及 31 省，共 128 个组合。
- Pages 发布工作流使用静态产物白名单，排除 `.git`、本地密钥、内部池与中间状态。自动采集完成后触发重新部署，机器人提交不会漏发页面。
- 全量抓取保持默认 `full`，重点省份预设更新为本次关注的七省，工作流时区统一为 `Asia/Shanghai`。

## 当前数据与未完成项

本地首次检查的快照（2026-11-03，原仓库记录时间）：

|运营商|全国公示条目|省级快照|
|---|---:|---:|
|移动|1542|31 省|
|联通|3850|31 省|
|电信|313|湖南 1 省|
|广电|139|31 省|

全国条目合计 5844。已有 98/128 个组合的真实快照。条目数量代表存储的公示记录，不是已核实全量或当前可办套餐数量；其中可能含停售业务、适用人群及地区限制。

江苏、上海、浙江电信的省级全量采集尚未完成。上游统一电信接口只配置全国与湖南；其余省份不能凭空推算 provCode。页面提供官方入口，并允许添加已核实的本机自定义记录；自定义记录不属于官方自动抓取数据。

已确认的江苏官方页面：https://wapjs.189.cn/mall/pages/feePart/index.html
浙江官方资费入口：https://www.189.cn/jtzfzq/zj
上海链接为官方省份入口，尚未完成浏览器内容核验：https://www.189.cn/jtzfzq/sh

本地已通过数据模型、原项目回归与静态包完整性检查。浏览器交互与截图验证尚未完成，官方接口实时请求尚未完成。本次修改保留上游 AES-CBC / AES-ECB、联通分段去重、广电 JSON POST 抓取实现，不声称新增过实时验证。

项目仓库已创建：https://github.com/JayChou0609/carrier-tariff-personal 。基于原项目建立公开副本并上传本次开发源码，保留 MIT 许可与上游历史。GitHub Pages 发布结果以仓库 Actions 的 Deploy GitHub Pages 工作流为准。

## 本机运行与验证

```sh
python3 -m http.server 8765 --bind 127.0.0.1
# 浏览器打开 http://127.0.0.1:8765/custom/
```

需要通过 HTTP 服务读取 JSON，不能直接双击 HTML 后期待浏览器允许跨文件 fetch。

```sh
pip install -r requirements.txt
python3 tests/test_diff.py
python3 tests/test_final_regressions.py
python3 -m unittest discover -s tests -p 'test_personal*.py' -v
node tests/test_personal.js
node --check custom/app.js
python3 scripts/build_coverage.py
python3 scripts/prepare_pages.py --repo YOUR_ACCOUNT/carrier-tariff-personal
```

## GitHub Pages 发布

1. 在自己的 GitHub 账号下创建公开仓库，例如 `carrier-tariff-personal`，将此项目完整源码（保留隐藏的 `.github/`）提交到 `main`。不要把新开发内容推到原作者仓库。
2. 仓库 `Settings → Pages → Build and deployment → Source` 选择 **GitHub Actions**。
3. `Actions → Deploy GitHub Pages → Run workflow`。发布工作流会测试、打包并部署，URL 以 Actions 实际输出为准。
4. 查看三个抓取工作流是否启用。默认全量；不需要配置通知 Secrets。采集成功后页面重新部署。

公开仓库 Pages 与 Actions 按 GitHub 当前免费方案和使用限制运行；Pages 提供静态网页托管，不能在网页中直接运行 Python。加解密及跨域接口采集在 Actions 中执行，浏览器只读取 JSON 快照。

## 文件

- `custom/`：新增个性化页面、样式与数据模型。
- `scripts/build_coverage.py`：从已有快照生成覆盖清单。
- `scripts/prepare_pages.py`：生成 `_pages/` 静态发布产物。
- `.github/workflows/pages.yml`：GitHub Pages 发布及采集后部署。
- `tests/test_personal.js`、`tests/test_personal_data.py`：新增数据处理及发布包检查。

个人收藏按运营商、地区、业务 ID 分开，避免跨省同名业务互相覆盖。所有个人数据只保存在浏览器本机，不跨设备同步；清理浏览器数据前请导出配置。
