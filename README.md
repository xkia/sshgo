ssh-auto-login-manage
=====================

SSH auto login without password and managing ssh hosts list on Mac OSX & Linux.

You can use these scripts instead of SecureCRT, xshell.

Refer to [ssh-auto-login](https://github.com/liaohuqiu/ssh-auto-login) and [sshgo](https://github.com/emptyhua/sshgo).

###How to use
1. `git clone https://github.com/flying5/ssh-auto-login-manage.git`
2. Modify file `/path/to/ssh-auto-login-manage/hosts`, use your hosts, you can set the special username & password & id_file for each hostname, and support the split with blankspace:

    ```
    deploy
        1.1.1.1  user1  password1
        2.2.2.2  user2  #use Public key authentication
        3.3.3.3  user3 -i /path/to/id_file.pem  #use id file to login
    Online-1
        4.4.4.4 user password #the first node will default as the below server's jumper server,if below server with section of indent
        intenal.server # below servers will use 4.4.4.4 as the jumper server
            10.0.2.10 user3 password3
            10.0.2.11 user4 password4
    Online-2
        5.5.5.5:22222 user5 password5 #use the special port
        6.6.6.6 user6 password6
    ```
4. Run script `./sshgo`, or you can alias `sshgo` command, add the line to the end of ~/.bash_profile and source it:
 * alias sshgo='/path/to/ssh-auto-login-manage/sshgo'
5. enjoy the `sshgo`.

###screenshot
![screenshot](https://github.com/upton/ssh-auto-login-manage/blob/master/screenshot.png)

-----
### 说明

* ssh免密码自动登录和主机管理，可以替代SecureCRT的自动登录。
* Mac下的term功能较弱，无法提供像SecureCRT那样方便的主机管理和自动登录功能。在网上找到用expect做自动登录的项目ssh-auto-login，和一个用python写的主机管理界面，于是把两个工程合并在一起，就是现在这个工程了。
* 参考了 [ssh-auto-login](https://github.com/liaohuqiu/ssh-auto-login) and [sshgo](https://github.com/emptyhua/sshgo)

####  以上为原作者的记录说明，在此基础上增加了如下功能：

* 针对部分服务器登录后的最后一句话非"Last login"，因此将需要jumper和直连的进行了拆分:auto_login.exp(直连方式)，auto_login_jumper.exp (跳板方式)
* 其次，增加了部分服务器对MFA验证的支持，引入"[oath-toolkit](https://www.nongnu.org/oath-toolkit/)"工具，进行二次登录验证码的获取，实现脚本文件为"oath.sh"，维护多screet

```shell
# aoth-toolkit 工具的安装可借助brew进行安装
brew install oath-toolkit
```

* 多screet维护在MFS.list文件中

```shell
# 命名(所谓关键字查找) screet 方式 
ha Y3ZYADXJGLFJR6U2 totp
```
#### 更新记录
* 20190705 在sshgo原有的基础上增加MFA的支持 MFA 和pem 无法同时存在，后期考虑优化
* 20190706 host文件中将#后面的文字作为选项备注显示在屏幕上 
* 20190903 增加ssgho3对python3的支持，因系统安装的python为2版本，增加sshgo.sh文件来调整运行环境

