"""
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

@file core.py
@author Varun Prasad (varun.prasad@riftio.com)
@date 09-Jul-2016

"""

class DtsHandler(object):
    """A common class to hold the barebone objects to build a publisher or
    subscriber
    """
    def __init__(self, log, dts, loop):
        """Constructor

        Args:
            log : Log handle
            dts : DTS handle
            loop : Asyncio event loop.
        """
        # Reg handle
        self.reg = None
        self.log = log
        self.dts = dts
        self.loop = loop
