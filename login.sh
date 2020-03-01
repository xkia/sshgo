#!/bin/sh
cd "`dirname $0`"
BASE_HOME=`pwd`

host=$1
port=$2
user=$3
password=$4
id_file=$5
if [ "$5" == "MFA" ]; then
	./auto_login_go.exp $host $port $user $password
elif [ "$5" == "SFTP" ]; then
	./auto_login_sftp.exp $host $port $user $password
elif [ "$5" == "TELNET" ]; then
	./auto_telnet.exp $host $port
elif [ $5 ] ; then
	./auto_login_with_id_file.exp $host $port $user $id_file
else
	./auto_login.exp $host $port $user $password
fi
