# 本机IOS CLI兼容实测

2026-10-13在独立c2621实例、既有c2600-i-mz.121-3.T镜像查询：

- `traceroute 10.5.2.2 ?`与`traceroute ip 10.5.2.2 ?`均只显示`<cr>`。
- `traceroute ip 10.5.2.2 timeout ?`、`... timeout 1 probe ?`均返回`% Unrecognized command`。不能照搬现代IOS单行timeout/probe选项。
- 裸`traceroute`显示`Protocol [ip]:`，输入空或`ip`均返回`% Unknown protocol`。没有把这种交互序列写入正式spec。
- `traceroute ip`没有目标返回`% Unrecognized host or address`。

第一次探测脚本错误地把Telnet碎片当完整交互提示，造成答案错位；已改成完整提示匹配重查。随后输入协议名失败是实际IOS输出。临时独立实例每次均停止，不触碰主线7200端口。

主线实验5首次正常trace已显示第一跳10.5.1.1三个RTT，第二跳目标两个RTT，随后30秒提示符超时；这是执行器等待上限触发，不能宣称协议抓包验收成功。解决路径是扩大命令等待时间；若需要限制探测时间，由运行器在若干秒后发送IOS中断字符Ctrl-Shift-6并读取实际prompt，协议门禁仍必须从真实pcap找到ICMP type11/code0。不能以“命令被中断”替代抓包门禁。
