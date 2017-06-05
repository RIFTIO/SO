#!/usr/bin/env bash
# 
#   Copyright 2016 RIFT.IO Inc
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# Author(s): Jeremy Mordkoff, Lezz Giles
# Creation Date: 08/29/2016
# 
#

# BUILD.sh
#
# This is a top-level build script for RIFT.io
#
# Arguments and options: use -h or --help
#
# dependencies -- requires sudo rights

# Defensive bash programming flags
set -o errexit    # Exit on any error
trap 'echo ERROR: Command failed: \"$BASH_COMMAND\"' ERR
set -o nounset    # Expanding an unset variable is an error.  Variables must be
                  # set before they can be used.

###############################################################################
# Options and arguments

# There 
params="$(getopt -o suhb: -l install-so,install-ui,no-mkcontainer,build-ui:,help --name "$0" -- "$@")"
if [ $? != 0 ] ; then echo "Failed parsing options." >&2 ; exit 1 ; fi

eval set -- $params

installSO=false
installUI=false
runMkcontainer=true
UIPathToBuild=

while true; do
    case "$1" in
	-s|--install-so) installSO=true; shift;;
	-u|--install-ui) installUI=true; shift;;
	-b|--build-ui) shift; UIPathToBuild=$1; shift;;
	--no-mkcontainer) runMkcontainer=false; shift;;
	-h|--help)
	    echo
	    echo "NAME:"
	    echo "  $0"
	    echo
	    echo "SYNOPSIS:"
	    echo "  $0 -h|--help"
	    echo "  $0 [-s] [-u|-b PATH-TO-UI-REPO] [PLATFORM_REPOSITORY] [PLATFORM_VERSION]"
	    echo
	    echo "DESCRIPTION:"
	    echo "  Prepare current system to run SO and UI.  By default, the system"
	    echo "  is set up to support building SO and UI; optionally, either or"
	    echo "  both SO and UI can be installed from a Debian package repository."
	    echo
	    echo "  -s|--install-so:  install SO from package"
	    echo "  -u|--install-ui:  install UI from package"
	    echo "  -b|--build-ui PATH-TO-UI-REPO:  build the UI in the specified repo"
	    echo "  --no-mkcontainer: do not run mkcontainer, used for debugging script"
	    echo "  PLATFORM_REPOSITORY (optional): name of the RIFT.ware repository."
	    echo "  PLATFORM_VERSION (optional): version of the platform packages to be installed."
	    echo
	    exit 0;;
	--) shift; break;;
	*) echo "Not implemented: $1" >&2; exit 1;;
    esac
done

if $installUI && [[ $UIPathToBuild ]]; then
    echo "Cannot both install and build the UI!"
    exit 1
fi

if [[ $UIPathToBuild && ! -d $UIPathToBuild ]]; then
    echo "Not a directory: $UIPathToBuild"
    exit 1
fi

# Turn this on after handling options, so the output doesn't get cluttered.
set -x             # Print commands before executing them

###############################################################################
# Find the platform
PYTHON=python
if [[ ! -f /usr/bin/python ]]; then
  PYTHON=python3
fi

if $PYTHON -mplatform | grep -qi fedora; then
    PLATFORM=fc20
elif $PYTHON -mplatform | grep -qi ubuntu; then
    PLATFORM=ub16
else
    echo "Unknown platform"
    exit 1
fi

###############################################################################
# Set up repo and version

if [[ $PLATFORM == ub16 ]]; then
    PLATFORM_REPOSITORY=${1:-OSM}
    PLATFORM_VERSION=${2:-4.4.2.0.60195}
elif [[ $PLATFORM == fc20 ]]; then
    PLATFORM_REPOSITORY=${1:-OSM}  # change to OSM when published
    PLATFORM_VERSION=${2:-4.4.2.0.60195}
else
    echo "Internal error: unknown platform $PLATFORM"
    exit 1
fi

###############################################################################
# Main block

# Disable apt-daily.service and apt-daily.timer

DAILY_TIMER='apt-daily.timer'
DAILY_SERVICE='apt-daily.service'
if [ $(systemctl is-active $DAILY_TIMER) = "active" ]
then
    systemctl stop $DAILY_TIMER
    systemctl disable $DAILY_TIMER
    systemctl disable $DAILY_SERVICE
fi

# must be run from the top of a workspace
cd $(dirname $0)

# inside RIFT.io this is an NFS mount
# so just to be safe
test -h /usr/rift && sudo rm -f /usr/rift

if [[ $PLATFORM == ub16 ]]; then
    # enable the right repos
    curl http://repos.riftio.com/public/xenial-riftware-public-key | sudo apt-key add -
    # the old mkcontainer always enabled release which can be bad
    # so remove it
    sudo rm -f /etc/apt/sources.list.d/release.list /etc/apt/sources.list.d/rbac.list /etc/apt/sources.list.d/OSM.list
    # always use the same file name so that updates will overwrite rather than enable a second repo
    sudo curl -o /etc/apt/sources.list.d/RIFT.list http://buildtracker.riftio.com/repo_file/ub16/${PLATFORM_REPOSITORY}/ 
    sudo apt-get update
        
    # and install the tools
    sudo apt remove -y rw.toolchain-rwbase tcpdump
    sudo apt-get install -y --allow-downgrades rw.tools-container-tools=${PLATFORM_VERSION} rw.tools-scripts=${PLATFORM_VERSION} python 
elif [[ $PLATFORM == fc20 ]]; then
    # get the container tools from the correct repository
    sudo rm -f /etc/yum.repos.d/private.repo
    sudo curl -o /etc/yum.repos.d/${PLATFORM_REPOSITORY}.repo \
	 http://buildtracker.riftio.com/repo_file/fc20/${PLATFORM_REPOSITORY}/ 
    sudo yum install --assumeyes rw.tools-container-tools rw.tools-scripts
else
    echo "Internal error: unknown platform $PLATFORM"
    exit 1
fi

# enable the OSM repository hosted by RIFT.io
# this contains the RIFT platform code and tools
# and install of the packages required to build and run
# this module
if $runMkcontainer; then
    if [[ $PLATFORM == ub16 ]]; then
        sudo apt-get install -y libxml2-dev libxslt-dev python3-crypto
    elif [[ $PLATFORM == fc20 ]]; then
        sudo yum-install --assumeyes libxml2-devel libxslt-devel python3-crypto
    fi
    sudo /usr/rift/container_tools/mkcontainer --modes build --modes ext --repo ${PLATFORM_REPOSITORY}
    sudo pip3 install lxml==3.4.0
fi


if [[ $PLATFORM == ub16 ]]; then
    # install the RIFT platform code:
    # remove these packages since some files moved from one to the other, and one was obsoleted
    # ignore failures

    PACKAGES="rw.toolchain-rwbase rw.toolchain-rwtoolchain rw.core.mgmt-mgmt rw.core.util-util \
	            rw.core.rwvx-rwvx rw.core.rwvx-rwdts rw.automation.core-RWAUTO"
    # this package is obsolete.
    OLD_PACKAGES="rw.core.rwvx-rwha-1.0"
    for package in $PACKAGES $OLD_PACKAGES; do
        sudo apt remove -y $package || true
    done

    packages=""
    for package in $PACKAGES; do
        packages="$packages $package=${PLATFORM_VERSION}"
    done
    sudo apt-get install -y --allow-downgrades $packages

    sudo apt-get install python-cinderclient
    
    sudo chmod 777 /usr/rift /usr/rift/usr/share
    
    if $installSO; then
	sudo apt-get install -y \
	     rw.core.mano-rwcal_yang_ylib-1.0 \
	     rw.core.mano-rwconfig_agent_yang_ylib-1.0 \
	     rw.core.mano-rwlaunchpad_yang_ylib-1.0 \
	     rw.core.mano-mano_yang_ylib-1.0 \
	     rw.core.mano-common-1.0 \
	     rw.core.mano-rwsdn_yang_ylib-1.0 \
	     rw.core.mano-rwsdnal_yang_ylib-1.0 \
	     rw.core.mano-rwsdn-1.0 \
	     rw.core.mano-mano-types_yang_ylib-1.0 \
	     rw.core.mano-rwcal-cloudsim-1.0 \
	     rw.core.mano-rwcal-1.0 \
	     rw.core.mano-rw_conman_yang_ylib-1.0 \
	     rw.core.mano-rwcalproxytasklet-1.0 \
	     rw.core.mano-rwlaunchpad-1.0 \
	     rw.core.mano-rwcal-openmano-vimconnector-1.0 \
	     rw.core.mano-rwcal-propcloud1-1.0 \
	     rw.core.mano-lpmocklet_yang_ylib-1.0 \
	     rw.core.mano-rwmon-1.0 \
	     rw.core.mano-rwcloud_yang_ylib-1.0 \
	     rw.core.mano-rwcal-openstack-1.0 \
	     rw.core.mano-rw.core.mano_foss \
	     rw.core.mano-rwmon_yang_ylib-1.0 \
	     rw.core.mano-rwcm-1.0 \
	     rw.core.mano-rwcal-mock-1.0 \
	     rw.core.mano-rwmano_examples-1.0 \
	     rw.core.mano-rwcal-cloudsimproxy-1.0 \
	     rw.core.mano-models-1.0 \
	     rw.core.mano-rwcal-aws-1.0
    fi
    
    if $installUI; then
	sudo apt-get install -y \
	     rw.ui-about \
	     rw.ui-logging \
	     rw.ui-skyquake \
	     rw.ui-accounts \
	     rw.ui-composer \
	     rw.ui-launchpad \
	     rw.ui-debug \
	     rw.ui-config \
	     rw.ui-dummy_component
    fi
elif [[ $PLATFORM == fc20 ]]; then
    
    temp=$(mktemp -d /tmp/rw.XXX)
    pushd $temp
    
    # yum does not accept the --nodeps and --replacefiles options so we
    # download first and then install
    yumdownloader rw.toolchain-rwbase-${PLATFORM_VERSION} \
		  rw.toolchain-rwtoolchain-${PLATFORM_VERSION} \
		  rw.core.mgmt-mgmt-${PLATFORM_VERSION} \
		  rw.core.util-util-${PLATFORM_VERSION} \
		  rw.core.rwvx-rwvx-${PLATFORM_VERSION} \
		  rw.core.rwvx-rwha-1.0-${PLATFORM_VERSION} \
		  rw.core.rwvx-rwdts-${PLATFORM_VERSION} \
		  rw.automation.core-RWAUTO-${PLATFORM_VERSION}
    
    # Install one at a time so that pre-installed packages will not cause a failure
    for pkg in *rpm; do
	# Check to see if the package is already installed; do not try to install
	# it again if it does, since this causes rpm -i to return failure.
	if rpm -q $(rpm -q -p $pkg) >/dev/null; then
	    echo "WARNING: package already installed: $pkg"
	else
	    sudo rpm -i --replacefiles --nodeps $pkg
	fi
    done
    
    popd
    rm -rf $temp
    
    # this file gets in the way of the one generated by the build
    sudo rm -f /usr/rift/usr/lib/libmano_yang_gen.so


    sudo chmod 777 /usr/rift /usr/rift/usr/share

    if $installSO; then
	sudo apt-get install -y \
	     rw.core.mc-\*-${PLATFORM_VERSION}
    fi
    
    if $installUI; then
	sudo apt-get install -y \
	     rw.ui-about-${PLATFORM_VERSION} \
	     rw.ui-logging-${PLATFORM_VERSION} \
	     rw.ui-skyquake-${PLATFORM_VERSION} \
	     rw.ui-accounts-${PLATFORM_VERSION} \
	     rw.ui-composer-${PLATFORM_VERSION} \
	     rw.ui-launchpad-${PLATFORM_VERSION} \
	     rw.ui-debug-${PLATFORM_VERSION} \
	     rw.ui-config-${PLATFORM_VERSION} \
	     rw.ui-dummy_component-${PLATFORM_VERSION}
    fi

else
    echo "Internal error: unknown platform $PLATFORM"
    exit 1
fi

# If you are re-building SO, you just need to run
# these two steps
if ! $installSO; then
    make -j16 
    sudo make install
fi    

if [[ $UIPathToBuild ]]; then
    make -C $UIPathToBuild -j16
    sudo make -C $UIPathToBuild install
fi

echo "Creating Service ...."
sudo $(dirname $0)/create_launchpad_service

