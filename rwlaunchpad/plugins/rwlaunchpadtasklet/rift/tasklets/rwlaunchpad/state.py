
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

import tornado.web

from . import message


class StateHandler(tornado.web.RequestHandler):
    def options(self, *args, **kargs):
        pass

    def set_default_headers(self):
        self.set_header('Access-Control-Allow-Origin', '*')
        self.set_header('Access-Control-Allow-Headers',
                        'Content-Type, Cache-Control, Accept, X-Requested-With, Authorization')
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, PUT, DELETE')

    def initialize(self, log, loop):
        self.log = log
        self.loop = loop

    def success(self, messages):
        success = self.__class__.SUCCESS
        return any(isinstance(msg, success) for msg in messages)

    def failure(self, messages):
        failure = self.__class__.FAILURE
        return any(isinstance(msg, failure) for msg in messages)

    def started(self, messages):
        started = self.__class__.STARTED
        return any(isinstance(msg, started) for msg in messages)

    def status(self, messages):
        if self.failure(messages):
            return "failure"
        elif self.success(messages):
            return "success"
        return "pending"

    def notifications(self, messages):
        notifications = {
                "errors": list(),
                "events": list(),
                "warnings": list(),
                }

        for msg in messages:
            if isinstance(msg, message.StatusMessage):
                notifications["events"].append({
                    'value': msg.name,
                    'text': msg.text,
                    'timestamp': msg.timestamp,
                    })
                continue

            elif isinstance(msg, message.WarningMessage):
                notifications["warnings"].append({
                    'value': msg.text,
                    'timestamp': msg.timestamp,
                    })
                continue

            elif isinstance(msg, message.ErrorMessage):
                notifications["errors"].append({
                    'value': msg.text,
                    'timestamp': msg.timestamp,
                    })
                continue

            elif isinstance(msg, message.FilenameMessage):
                notifications["filename"] = msg.text
                continue

            self.log.warning('unrecognized message: {}'.format(msg))

        return notifications

    def get(self, transaction_id):
        if transaction_id not in self.application.messages:
            raise tornado.web.HTTPError(404, "unrecognized transaction ID")

        messages = self.application.messages[transaction_id]
        messages.sort(key=lambda m: m.timestamp)

        if not self.started(messages):
            raise tornado.web.HTTPError(404, "unrecognized transaction ID")

        notifications = self.notifications(messages)
        notifications["status"] = self.status(messages)

        self.write(tornado.escape.json_encode(notifications))
