#!/bin/sh
cd "`dirname $0`"
BASE_HOME=`pwd`

python3 ./sshgo.py $1
