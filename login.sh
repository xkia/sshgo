#!/bin/sh
cd "`dirname $0`"
BASE_HOME=`pwd`

host=$1
port=$2
user=$3
password=$4
type=$5 #id_file
sarg=$6
if [[ "$type" =~ ^MFA* ]] && [[ $sarg ]]; then
	secret=${type#*MFA:}
	./auto_login_jumper_domain.exp $host $port $user $password "ssh" $secret $sarg
elif [[ "$type" =~ ^MFA* ]]; then
	secret=${type#*MFA:}
	./auto_login.exp $host $port $user $password "ssh" $secret 
elif [[ "$type" =~ ^SFTP* ]]; then
	secret=${type#*SFTP:}
	./auto_login.exp $host $port $user $password "sftp" $secret
elif [ $type ] ; then
	./auto_login_with_id_file.exp $host $port $user $type
else
	./auto_login.exp $host $port $user $password
fi
