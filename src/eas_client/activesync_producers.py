from twisted.internet.defer import succeed
from twisted.web.iweb import IBodyProducer
from zope.interface import implements
from dewbxml import wbxmlparser, wbxmlreader, wbxmldocument, wbxmlelement, wbxmlstring

class WBXMLProducer(object):
	implements(IBodyProducer)
	page_num = None
	def __init__(self, wbdoc):
		self.wb = wbdoc
		self.body = str(self.wb.tobytes(restrict_page_num=self.page_num))
		self.length = len(self.body)
	def startProducing(self, consumer):
		#print "BODY",self.body.encode("hex"), self.wb
		consumer.write(self.body)
		return succeed(None)
	def pauseProducing(self): pass
	def stopProducing(self): pass

def convert_array_to_children(in_elem, in_val):
	if isinstance(in_val, list):
		for v in in_val:
			add_elem = wbxmlelement(v[0])
			in_elem.addchild(add_elem)
			convert_array_to_children(add_elem, v[1])
	elif in_val != None:
		in_elem.addchild(wbxmlstring(in_val))

def convert_dict_to_wbxml(indict):
	wb = wbxmldocument()
	wb.encoding = "utf-8"
	wb.version = "1.3"
	wb.schema = "activesync"
	assert len(indict) == 1 # must be only one root element
	#print "Root",indict.keys()[0]
	root = wbxmlelement(indict.keys()[0])
	wb.addchild(root)
	convert_array_to_children(root, indict.values()[0])
	return wb
		
class FolderSyncProducer(WBXMLProducer):
	def __init__(self, sync_key):
		self.page_num = 7
		wb = convert_dict_to_wbxml({
			"FolderSync": [
				("SyncKey", str(sync_key))
			]
		});
		return WBXMLProducer.__init__(self, wb)

class SyncProducer(WBXMLProducer):
	def __init__(self, collection_id, sync_key):
		self.page_num = 0
		wbdict = {
			"Sync": [
				("Collections", [
					("Collection", [
						("SyncKey", str(sync_key)),
						("CollectionId", str(collection_id)),
						("DeletesAsMoves", "1"),
					])
				])
			]
		}
		if sync_key != 0:
			wbdict["Sync"][0][1][0][1].append(("GetChanges","1"))
			wbdict["Sync"][0][1][0][1].append(("WindowSize","512"))
		wb = convert_dict_to_wbxml(wbdict)
		return WBXMLProducer.__init__(self, wb)

class ProvisionProducer(WBXMLProducer):
	def __init__(self, policyKey=None):
		self.page_num = 14
		wbdict = {
			"Provision": [
				("Policies", [
					("Policy", [
						("PolicyType", "MS-EAS-Provisioning-WBXML"),
					])
				])
			]
		}

		if policyKey != None:
			wbdict["Provision"][0][1][0][1].append(("PolicyKey",str(policyKey)))
			wbdict["Provision"][0][1][0][1].append(("Status","1"))
		
		wb = convert_dict_to_wbxml(wbdict)

		return WBXMLProducer.__init__(self, wb)