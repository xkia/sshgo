#! /bin/bash
cd "`dirname $0`"
BASE_HOME=`pwd`

if [ $# -ne 1 ]
then
    echo "Usage:ju hbase1"
    echo "mapping is following:"
    exit 1
fi

n=$1
cmd_list="./cmd.list"
grep "^$n" $cmd_list &> /dev/null
if [ $? -ne 0 ]
then
   echo "pwd" 
fi
line=`grep "^$n" $cmd_list`
fix=`echo $line|awk -F':' '{print $1}'`
cmd=`echo $line|awk -F':' '{print $2}'`
if [ "$fix" == "$n" ]
then
  echo $cmd
fi
exit 0
