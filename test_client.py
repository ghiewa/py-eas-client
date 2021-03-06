import sys
from eas_client import *
from twisted.internet import reactor

# The autodiscovery implementation is very incomplete
#a = autodiscovery.AutoDiscover("foo@foo.com")
#d = a.autodiscover()
#d.addCallback(autodiscover_result)

if len(sys.argv) != 6:
	print "Usage: test_client.py <domain> <username> <password> <server hostname> <device ID>"
	sys.exit(1)

async = activesync.ActiveSync(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], True, device_id=sys.argv[5], verbose=True)

#def option_result(res):
#	print "Options",res
#async.get_options().addBoth(option_result)

def body_result(result):
	print "BODY RESULT",result
	print "BODY",result["Properties"]["Body"]
	reactor.stop()

def sync_result(result, fid, async):
	print "Sync result",result.keys()
	fetch_id = result.keys()[-5]
	async.add_operation(async.fetch, fid, fetch_id, 4, mimeSupport=2).addBoth(body_result)

def fsync_result(result, async):
	print "FolderSync",result
	for (fid,finfo) in result.iteritems():
		if finfo["DisplayName"] == "Inbox":
			print "INBOX",fid,finfo
			async.add_operation(async.sync, fid).addBoth(sync_result, fid, async)
			break

def prov_result(success, async):
	print "TEST Provision result",success, async
	if success == True:
		async.add_operation(async.folder_sync).addBoth(fsync_result, async)
	else:
		reactor.stop()

async.add_operation(async.provision).addBoth(prov_result, async)

reactor.run()