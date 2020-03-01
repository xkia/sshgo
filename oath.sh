#!/bin/bash
cd "`dirname $0`"
BASE_HOME=`pwd`
g_list="./MFA.list"
if [ $# -ne 1 ]
then
	n=ha
else
	n=$1
fi
line=`grep "^$n" $g_list`
fix=`echo $line |awk '{print $1}'`
code=`echo $line|awk '{print $2}'`
type=`echo $line|awk '{print $3}'`
if [ "$fix" == "$n" ]
then
	pwd=$(oathtool --${type} -b -d 6 ${code})
	echo $pwd
else
	echo "not find !"
fi
exit 0
