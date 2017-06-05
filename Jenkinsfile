pipeline {
	agent {
		label "pipeline"
	}
	stages {
		stage("Build") {
			agent {
				dockerfile true
			}
			steps {
				sh 'make NOT_DEVELOPER_BUILD=TRUE -j16 package'
				stash name: "deb-files", includes: ".build/*.deb"
			}
		}
		stage("Repo Component") {
			agent {
				docker {
					image 'debian:stable'
					args '--net=deb-repo-master'
				}
			}
			steps {
				unstash "deb-files"
				sh '''
					apt-get update && apt-get -y install rsync
					rsync -Pr .build/*.deb deb-repo-master:/var/lib/deb-repo/ReleaseONE/incoming/unstable/SO/
					ssh deb-repo-master 'process-incoming'
					'''
			}
		}
	}
}
