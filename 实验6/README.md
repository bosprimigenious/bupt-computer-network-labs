# 实验6：综合网络实践

**三厂商完整实验 NOT READY：当前没有 Juniper/H3C 镜像或实验室设备。** 已实现自己的三厂商配置生成器、真实 console 验收工具和纯 Cisco 功能预演。生成成功或预演通过均不等于三厂商实验通过。

## PPT 对照与设计

依据 实验6讲义（课程讲义需自行取得） 第2～5页：一个子网12台设备，其中4台路由器，包含1台Juniper、1～2台Cisco、1～2台H3C；自设计逻辑网络，验证PC互通和动态路由学习。第21～33页给出静态路由/RIP命令示例。讲义没有强制必须选RIP，因此本设计参考agicy实验6选择OSPF area 0。日期、终端服务器地址、接口编号要按本届现场重新确认。

主方案 [topology.json](topology.json)：R1为Juniper，R2为Cisco，R3/R4为H3C；另有PC1～PC8。路由器两端口及PC接口接入公共以太网交换网络，共16个接口；transit地址为205.161.255.1～4/24，四个LAN为205.161.1～4.0/24，网关尾号254，每LAN两台PC尾号1/2。学号（已隐去；地址参数161），926 % 255 = 161。这是自己的逻辑划分，不复制旧组204.210地址。

| 路由器 | 厂商 | transit接口（示例，现场修改） | LAN接口（示例，现场修改） |
|---|---|---|---|
| R1 | Juniper | fe-0/0/0 | fe-0/0/1 |
| R2 | Cisco | GigabitEthernet0/0 | GigabitEthernet0/1 |
| R3 | H3C | GigabitEthernet0/0 | GigabitEthernet0/1 |
| R4 | H3C | GigabitEthernet0/0 | GigabitEthernet0/1 |

三厂商配置相同区域和/24广播网络，默认OSPF hello/dead为10/40秒。LAN设passive（H3C为silent），避免与PC建立邻居，LAN网络仍被宣告。广播网络DROTHER之间可以2WAY，不能要求每对邻居都FULL。Juniper J4350只生成路由配置；若换vSRX，设置srx_security=true生成隔离实验区域所需OSPF/ping及内部转发策略。

## 配置生成与部署

在课程根目录：

```sh
_环境/.venv/bin/python 实验6/generate.py
```

输出commands/R1～R4.txt和PC1～PC8.txt。PC命令面向VPCS；物理PC手工设置相同地址/24和网关。生成器拒绝覆盖不同内容的文件；改拓扑前先快照，先生成到新目录核对：

```sh
_环境/.venv/bin/python 实验6/generate.py --output /tmp/lab6-new-commands
```

先按现场型号改接口，再生成、部署、验收；反过来会把命令下到错误接口。部署前保存设备原配置，Juniper先commit check；不清空设备，不改变共享管理接口，不套用旧密码。

## 环境硬阻塞

已探测 /Applications、~/GNS3/images、~/VirtualBox VMs、~/Documents/Virtual Machines、~/Parallels 和课程_环境/ios：无Juniper/H3C镜像或虚拟机平台，只有2份Cisco IOS。用户已明确当前没有厂商镜像/设备。

推荐课程实验室实物设备；另一条路径是在具备厂商镜像的x86 Linux/KVM主机上远端仿真，本机通过console配置和采集。Juniper官方 [vSRX KVM要求](https://www.juniper.net/documentation/us/en/software/vsrx/vsrx-consolidated-deployment-guide/vsrx-kvm/topics/concept/security-vsrx-system-requirement-with-kvm.html) 和 [安装命令](https://www.juniper.net/documentation/us/en/software/vsrx/vsrx-consolidated-deployment-guide/vsrx-kvm/topics/task/security-vsrx-with-kvm-installing.html) 使用x86_64和QCOW2镜像；H3C [官方HCL](https://www.h3c.com/cn/Service/Document_Software/Software_Download/Other_Product/H3C_Cloud_Lab/Catalog/HCL/) 是Windows模拟平台。当前arm64 Mac安装GNS3界面不会自动得到另外两家设备。

具体缺少：三厂商设备/镜像、真实接口与连线、已登录的12个console端点，或现场8台PC的等价真实ping日志。没有这些输入，入口拒绝运行并返回NOT READY。

## 三厂商真实验收

将endpoints.example.json复制为自己的端点文件并填真实host/port。旧PPT服务器IP没有写成默认连接。先登录console并手动部署commands；Cisco处于#，H3C处于<...>，Juniper处于CLI的>（root shell先cli）。自动PC采集当前支持VPCS，物理PC要单独采集并人工审计。

```sh
_环境/.venv/bin/python 实验6/verify_remote.py --endpoints /path/to/endpoints.json
```

工具只读采集，不登录、不存密码、不自动覆盖配置。每台路由器采集version、配置、接口、邻居和OSPF路由，检查厂商、至少2个FULL及其余3个router-id、3条远端LAN路由；8台PC检查地址/网关和56方向互ping，每次5个响应全成功，另有未分配地址负对照。原始console和result.json留在evidence/时间戳。缺端点已实际运行，返回2、NOT READY；真实三厂商测试未跑。

## 本机Cisco功能预演

[cisco-proxy](cisco-proxy/) 使用4台c3640路由器、8台c2621模拟PC、1台NM-16ESW交换机、16条连接，模拟相同transit、四LAN和OSPF。可验证真实IOS路由学习、8PC互通及抓包；不具备Juniper/H3C实现。

```sh
_环境/.venv/bin/python _环境/lab.py run 实验6/cisco-proxy
```

预演门禁：4路由各有3条远端OSPF路由和3邻居；56方向每向3轮5/5；未分配地址0/5；抓包含实际OSPF和ICMP。报告位于cisco-proxy/evidence/时间戳/result.json，其中READY仅表示纯Cisco功能预演通过，**实验6总体仍为NOT READY，直到真实三厂商验收通过**。

## 来源

主要参考 [agicy实验6](https://github.com/agicy/buptLab-network/tree/main/lab6-multivendor)，MIT，提交c5b562b625e04590932c5f62660d89f0b5ca00ee。沿用设备数据→厂商配置及共享transit+多LAN思路；自己的实现增加router-id、passive LAN、型号分支、覆盖保护和真实证据门禁。许可见资料/来源许可/agicy-buptLab-network-LICENSE.txt。重复参考项目已在课程外归档，不恢复工作目录副本。
