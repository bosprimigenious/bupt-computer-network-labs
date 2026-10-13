# 实验1 简单交换机配置

按本地讲义使用真实Cisco IOS：两台c3640 + NM-16ESW，三台c2621模拟PC。**历史运行READY；最新公共运行器改动尚未回归，当前提交不声明READY。**

## 运行

在课程根目录执行：

```sh
sh _环境/setup.sh
./run.sh 实验1
```

安装脚本使用Homebrew原生Dynamips和uv隔离Python环境；固定Python依赖见 `_环境/requirements.lock`。Python 3运行器直接驱动Dynamips官方hypervisor API，加载本目录 `lab1.net`，无需旧Python 2 Dynagen。不会调用参考仓库的全局杀进程脚本。

`run.sh` 每次从空NVRAM启动、重新下发 `commands/` 五份配置，采集现场证据，结束时只关闭自己启动的模拟器。工作目录位于本次 `evidence/时间/working/`，不会覆盖上次运行。7200与3004–3008是本实验专用端口；遇占用则报错，不能停掉别人的实例。

## 拓扑与地址

| 设备 | console | 配置 |
| --- | --- | --- |
| SW1 | 3004 | c3640，slot1 NM-16ESW，PC1接F1/11、PC2接F1/12 |
| SW2 | 3005 | c3640，slot1 NM-16ESW，PC3接F1/11 |
| PC1 | 3006 | c2621 F0/0，1.1.1.1/8 |
| PC2 | 3007 | c2621 F0/0，1.1.1.2/8 |
| PC3 | 3008 | c2621 F0/0，1.1.1.3/8 |

交换机双链路：SW1 F1/1 ↔ SW2 F1/2，SW1 F1/2 ↔ SW2 F1/1。端口保持VLAN1，STP保护二层冗余，不关闭STP。PPT端口3003/3004存在跨页不一致，我们统一使用上表。

第一部分验收PC1↔PC2；第二部分验收PC1↔PC3；运行器额外检查PC2↔PC3，共六个方向。每方向先保留一次ARP预热输出，再要求连续三轮各5/5。先等IOS引导、配置完成和STP收敛再测试；反过来可能把ARP/STP短暂丢包误判为配置失败。

## 证据与门禁

运行产生 `evidence/时间/result.json`、每台设备的 `*.console.log`、`hypervisor.log`和`dynamips.log`。检查真实接口up/up、实际running-config、STP转发/阻塞和六方向ping。任何命令拒绝、提示符超时或门禁失败均返回非零，并保留原始失败输出。

镜像只保留 `_环境/ios/` 一份。`confreg=0x2142`沿用PPT，会忽略startup-config；因此运行器每次都从commands重配，保证复现不依赖遗留状态。ARM版Dynamips是no-JIT解释器，性能与x86 JIT不同，但执行同一Cisco IOS。

原始上游资料已归档到课程目录外，本实验只使用自己的拓扑和配置。来源及许可见 `资料/来源说明.md` 和 `资料/来源许可/`。

## 历史验收

[2026-10-13完整结果](evidence/20261013-165945-057796/result.json)：九项门禁全部通过，18次ping均5/5，负对照0/5。运行器退出0，端口已释放。首轮4/5失败记录保留在 `evidence/20261013-165421-329584/`。

idlepc来自当轮真实采样，SW类选择0x604b99e8，PC类选择0x802c0698；候选和应用响应均记录在result.json。每次运行重新采样，不把本次地址硬编码给其他IOS版本。
