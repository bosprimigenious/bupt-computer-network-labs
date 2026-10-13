# 实验5：网络协议分析

拓扑、场景配置和HTTP代理分析脚本已实现。协议分析的完整运行验收必须同时满足IOS场景与真实pcap；尚未取得证据时为 **NOT READY**。

本地依据：`资料/讲义/实验5-讲义.ppt`第19～27页ARP、第28～34页ICMP、第41～43页收发全过程与HTTP代理。借鉴 Tingwuren 5.1～5.4 的小型抓包拓扑，当前只维护自己的五台设备、四条链路，多个场景顺序执行并恢复配置。

PC1=10.5.1.2/24、PC2=10.5.1.3/24，同接SW1；R1 F0/0=10.5.1.1/24；R1 F1/0=10.5.2.1/24连接PC3=10.5.2.2/24。PC各配置本网关。PC1和PC3链路均真实抓包。

运行 `./run.sh 实验5`，阶段见 `specification.json`：

1. 清ARP，同网ping并记录ARP请求/响应、缓存和ICMP回显。
2. 清ARP，跨网双向ping。PC1解析网关MAC；两个LAN抓包比较同一ICMP标识/序号的TTL减1、MAC改写与IP保持。
3. traceroute触发真实TTL超时ICMP11；访问无路由10.99.99.99触发ICMP3。
4. 添加静态ARP，查表确认，删除后查表确认消失。
5. 在隔离网络把PC2短暂改为PC1地址，R1清ARP后触发查询，采集GARP与两个MAC争用同IP的证据；恢复PC2原地址后重新验证通信。

IOS不是Windows XP。PPT的“动态ARP两分钟、最长十分钟”和“重复地址后Windows不能初始化协议栈”是旧Windows行为，不能套到IOS。这里记录实际IOS的缓存、重复IP报文和日志，不伪造旧操作系统结果。如老师要求复现Windows行为，需另加指定版本Windows环境，这一项不由IOS替代。

抓包后运行 `python3 实验5/analyze_capture.py 实验5/evidence/<本次目录>`；该脚本要求实际ARP1/2、ICMP0/8/11/3、GARP、重复IP两MAC以及跨网TTL与MAC变化。Wireshark过滤器可用 `arp`、`icmp.type == 11`、`icmp.type == 3`。

HTTP代理是同一实验的应用层子场景：`python3 实验5/http_proxy.py --output 实验5/evidence/<本次目录>/http`。本机三个真实TCP端点为client→proxy→origin；自动校验客户端绝对URL请求变为服务器路径请求、Via头、真实两条连接源端口、响应内容与事件时序。证据为http-events.json和http-result.json。PPT第41页要求分析HTTP代理流程，没有要求必须抓HTTP的TCP包；程序仍尝试tcpdump lo0，当前用户无/dev/bpf权限时保留失败日志，TCPpcap记可选缺口。`--require-pcap`启用更严格验收，无实际TCPpcap就返回NOT READY。
