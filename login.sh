#!/bin/bash

cd "`dirname $0`"
BASE_HOME=`pwd`

host="$1"
port="$2"
user="$3"
password="$4"
type="$5" #id_file
sarg="$6"

case "$type" in
  MFA:* )
    secret="${type#*MFA:}"
    if [ -n "$sarg" ]; then
      ./auto_login_jumper_domain.exp "$host" "$port" "$user" "$password" "ssh" "$secret" "$sarg"
    else
      ./auto_login.exp "$host" "$port" "$user" "$password" "ssh" "$secret"
    fi
    ;;
  SFTP:* )
    secret="${type#*SFTP:}"
    ./auto_login.exp "$host" "$port" "$user" "$password" "sftp" "$secret"
    ;;
  * )
    if [ -n "$type" ]; then
      ./auto_login_with_id_file.exp "$host" "$port" "$user" "$type"
    else
      ./auto_login.exp "$host" "$port" "$user" "$password"
    fi
    ;;
esac
