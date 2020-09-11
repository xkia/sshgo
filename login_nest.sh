#!/bin/sh
cd "`dirname $0`"
BASE_HOME=`pwd`

host=$1
port=$2
user=$3
password=$4
type=$5

s_host=$6
s_port=$7
s_user=$8
s_password=$9
s_arg=${!#}

if [[ "$type" =~ ^MFA* ]]; then
    secret=${type#*MFA:}
    ./auto_go.exp $host $port $user $password $secret $s_host $s_user $s_password $s_arg
else
    ./auto_login_jumper.exp $host $port $user $password $s_host $s_port $s_user $s_password
fi
