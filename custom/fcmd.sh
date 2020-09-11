#! /bin/bash
cd "`dirname $0`"
BASE_HOME=`pwd`

if [ $# -ne 1 ]
then
  echo ""
fi

n=$1
cmd_list="./cmd.list"
grep "^$n" $cmd_list &> /dev/null
if [ $? -ne 0 ]
then
  echo ""
fi
line=`grep "^$n" $cmd_list`
fix=`echo $line|awk -F':' '{print $1}'`
cmd=`echo $line|awk -F':' '{print $2}'`
if [ "$fix" == "$n" ]
then
  echo $cmd
fi
exit 0
