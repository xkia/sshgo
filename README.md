sshgo
---
SSH auto login without password and managing ssh hosts list on Mac OSX & Linux.

## How to use
1. Modify file `/path/to/sshgo/hosts`, use your hosts, you can set the special username & password & id_file for each hostname, and support the split with blankspace:

    ```bash
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
2. Run script `./sshgo.sh`, or you can alias `sshgo` command, add the line to the end of ~/.bash_profile and source it:

    ```bash
    alias sshgo='/path/to/sshgo/sshgo.sh'
    ```
3. enjoy the `sshgo`.

---
## Notes
* For some servers, the last sentence after login is not "Last login", so the jumper and direct connection are split: `auto_login.exp` (direct connection method), `auto_login_jumper.exp` (springboard method)
* Secondly, some servers have added support for MFA verification, relying on `auth.py` to obtain the second login verification code and maintain multiple screens
