#!/bin/bash

cd "`dirname $0`"
BASE_HOME=`pwd`

python3 -B ./sshgo.py "$@"
