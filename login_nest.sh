#!/bin/sh
cd "`dirname $0`"
BASE_HOME=`pwd`

host=$1
port=$2
user=$3
password=$4

s_host=$5
s_port=$6
s_user=$7
s_password=$8

if [ "$5 == 'MFA'" ]; then
    oath=`./oath.sh`
    echo $host $port $user $password $oath $s_host
    ./auto_go.exp $host $port $user $password $oath $s_host
else 
  echo "111"
#    ./auto_login_jumper.exp $host $port $user $password $s_host $s_port $s_user $s_password
fi
