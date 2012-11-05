from twisted.mail import imap4, maildir
from twisted.internet import reactor, defer, protocol
from twisted.cred import portal, checkers, credentials
from twisted.cred import error as credError
from zope.interface import implements
import time, os, random, sys, datetime, dateutil
from twisted.python import log
from email.Utils import formatdate

from eas_client import *

from cStringIO import StringIO
import email


MAILBOXDELIMITER = "."

log.startLogging(sys.stdout)

global_per_user_cache = {
    "mailbox": {}
}

class EASIMAPMailbox(object):
    implements(imap4.IMailbox)

    def __init__(self, path, info, async):
        self.collectionName = path.split(os.sep)[-1]
        print "Creating maildir", self.collectionName
        self.async = async
        self.folderinfo = info
        self.metadata = {}
        self.listeners = []
        self.messageObjects = {}
        self.initMetadata()
        self.dataCache = None

    def initMetadata(self):
        if not self.metadata.has_key('flags'):
            self.metadata['flags'] = {} # dict of message IDs to flags
        if not self.metadata.has_key('uidvalidity'):
            # create a unique integer ID to identify this version of
            # the mailbox, so the client could tell if it was deleted
            # and replaced by a different mailbox with the same name
            self.metadata['uidvalidity'] = random.randint(1000000, 9999999)
        if not self.metadata.has_key('uids'):
            self.metadata['uids'] = {}
        if not self.metadata.has_key('uidnext'):
            self.metadata['uidnext'] = 1 # next UID to be assigned

    def getHierarchicalDelimiter(self):
        return MAILBOXDELIMITER

    def getFlags(self):
        "return list of flags supported by this mailbox"
        return [r'\Seen', r'\Unseen']

    def fill_data_cache(self):
        d = self.async.add_operation(self.async.sync, self.folderinfo["ServerId"])
        d.addCallback(self.sync_result)
        d.addErrback(self.sync_err)
        return d

    def getMessageCount(self, ignore=None):
        print "Getting message count", self.collectionName
        assert self.dataCache != None # should have been filled in by account.select()
        return len(self.dataCache)

    def getRecentCount(self):
        return 0

    def getUnseenCount(self, ignore=None):
        print "Getting unseencount", self.collectionName
        assert self.dataCache != None # should have been filled in by account.select()
        unseencount = 0
        for msg in self.dataCache.values():
            if msg["ApplicationData"]["Read"] != "1":
                unseencount += 1
        return unseencount

    def isWriteable(self):
        return True

    def getUIDValidity(self):
        return self.metadata['uidvalidity']

    def _seqMessageSetToSeqDict(self, messageSet):
        """
        take a MessageSet object containing message sequence numbers,
        and return a dictionary mapping sequence number to filenames
        """
        # if messageSet.last is None, it means 'the end', and needs to
        # be set to a sane high number before attempting to iterate
        # through the MessageSet
        print "In _seqMessageSetToSeqDict", messageSet
        if not messageSet.last: messageSet.last = len(self.dataCache)-1
        seqMap = {}
        for messageNo in messageSet:
            seqMap[messageNo] = self.dataCache.keys()[messageNo-1]
        return seqMap

    def _uidMessageSetToSeqDict(self, messageSet):
        """
        take a MessageSet object containing UIDs, and return
        a dictionary mapping sequence numbers to serverIds
        """
        # if messageSet.last is None, it means 'the end', and needs to
        # be set to a sane high number before attempting to iterate
        # through the MessageSet
        if not messageSet.last:
            messageSet.last = self.metadata['uidnext']
        allUIDs = []
        print "In _uidMessageSetToSeqDict", messageSet
        allUIDs = [self.metadata['uids'][x] for x in self.dataCache.iterkeys()]
        allUIDs.sort()
        seqMap = {}
        for uid in messageSet:
            # the message set covers a span of UIDs. not all of them
            # will necessarily exist, so check each one for validity
            if uid in allUIDs:
                sequence = allUIDs.index(uid)+1
                seqMap[sequence] = self.dataCache.keys()[sequence-1]
        return seqMap

    def sync_result(self, sync_result):
        print "SYNC RESULT",sync_result.keys()
        if self.dataCache == None:
            self.dataCache = {}
        self.dataCache.update(sync_result)
        for server_id in self.dataCache.iterkeys():
            if server_id not in self.metadata['uids']:
                msg_info = self.dataCache[server_id]
                msg_uid = self.metadata['uidnext']
                self.metadata['uids'][server_id] = msg_uid
                self.metadata['flags'][msg_uid] = []
                if msg_info["ApplicationData"]["Read"] == "1":
                    self.metadata['flags'][msg_uid].append(r'\Seen')
                else:
                    self.metadata['flags'][msg_uid].append(r'\Unseen')
                self.metadata['uidnext'] = msg_uid+1
        for listener in self.listeners:
            listener.newMessages(self.getMessageCount(), None)

    def sync_err(self, err_val):
        print "SYNC ERR",err_val.value
        if err_val.value == "ActiveSync error 135":
            print "RETRY REQUEST..."
        return None


    def fetch_callback(self, ignore, messages, uid):
        return self.fetch(messages, uid)

    def fetch_finished(self, ignore, fetch_res):
        print "FETCH FINISHED",ignore,fetch_res
        return fetch_res

    def fetch(self, messages, uid):
        print "IMAP MBOX FETCH",messages,uid

        if self.dataCache == None:
            d = self.fill_data_cache()
            d.addCallback(self.fetch_callback, messages, uid)
            return d

        if uid:
            messagesToFetch = self._uidMessageSetToSeqDict(messages)
        else:
            messagesToFetch = self._seqMessageSetToSeqDict(messages)

        fetch_res = []
        for seq, server_id in messagesToFetch.items():
            uid = self.metadata["uids"][server_id]
            flags = self.metadata['flags'][uid]
            if server_id not in self.messageObjects:
                self.messageObjects[server_id] =  EASMessage(self.dataCache[server_id], uid, flags, self.async, self.folderinfo["ServerId"])
            fetch_res.append((seq, self.messageObjects[server_id]))
        print "Fetch res",fetch_res,"collecting messages"
        dlist = []
        for seqno, msg_object in fetch_res:
            if msg_object.data == None:
                dlist.append(msg_object.fillDataCache())
        d = defer.DeferredList(dlist)
        d.addCallback(self.fetch_finished, fetch_res)
        print "DLIST",dlist
        #reactor.callLater(0, d.callback, None)
        return d

    def getUID(self, messageNum):
        print "In getUid", messageNum
        return self.metadata['uids'].values()[messageNum]

    def getUIDNext(self):
        return self.metadata['uidnext']

    def addListener(self, listener):
        print "Add listener",listener
        self.listeners.append(listener)
        return True

    def removeListener(self, listener):
        self.listeners.remove(listener)
        return True

    def requestStatus(self, path):
        return imap4.statusRequestHelper(self, path)

    def addMessage(self, msg, flags=None, date=None):
        if flags is None: flags = []
        print "In addMessage", msg
        return self.maildir.appendMessage(msg).addCallback(
            self._addedMessage, flags)

    def _addedMessage(self, _, flags):
        # the first argument is the value returned from
        # MaildirMailbox.appendMessage. It doesn't contain any meaningful
        # information and can be discarded. Using the name "_" is a Twisted
        # idiom for unimportant return values.
        self._assignUIDs()
        
        #Get the last message uuid added to the mailbox
        chandlerUUID = self.maildir[-1]
        messageID = self.metadata['uids'][chandlerUUID]
        self.metadata['flags'][messageID] = flags
        self.saveMetadata()

    def saveMetadata(self):
        raise Exception("TODO")

    def store(self, messageSet, flags, mode, uid):
        if uid:
            messages = self._uidMessageSetToSeqDict(messageSet)
        else:
            messages = self._seqMessageSetToSeqDict(messageSet)
        setFlags = {}
        for seq, filename in messages.items():
            uid = self.getUID(seq)
            if mode == 0: # replace flags
                messageFlags = self.metadata['flags'][uid] = flags
            else:
                messageFlags = self.metadata['flags'].setdefault(uid, [])
                for flag in flags:
                    # mode 1 is append, mode -1 is delete
                    if mode == 1 and not messageFlags.count(flag):
                        messageFlags.append(flag)
                    elif mode == -1 and messageFlags.count(flag):
                        messageFlags.remove(flag)
            setFlags[seq] = messageFlags
        self.saveMetadata()
        return setFlags

    def expunge(self):
        "remove all messages marked for deletion"
        removed = []
        print "In expunge"
        return removed

    def destroy(self):
        "complete remove the mailbox and all its contents"
        raise imap4.MailboxException("Permission denied.")

class EASMessagePart(object):
    implements(imap4.IMessagePart)

    def __init__(self, mimeMessage):
        self.message = mimeMessage
        self.data = str(self.message)

    def getHeaders(self, negate, *names):
        #print "GET HEADERS",self.info["ApplicationData"], names, negate
        """
        Return a dict mapping header name to header value. If *names
        is empty, match all headers; if negate is true, return only
        headers _not_ listed in *names.
        """
        available_headers = ["From", "To", "Date", "Subject"]
        header_translation = {"Date":"DateReceived"}
        if not names: names = available_headers
        headers = {}
        if negate:
            for header in available_headers:
                if header.upper() not in names:
                    try:
                        headers[header.lower()] = self.info["ApplicationData"][header_translation[header]]
                    except:
                        headers[header.lower()] = self.info["ApplicationData"][header]
        else:
            for header in available_headers:
                if header.upper() in names:
                    try:
                        headers[header.lower()] = self.info["ApplicationData"][header_translation[header]]
                    except:
                        headers[header.lower()] = self.info["ApplicationData"][header]
        print "Return headers",headers
        return headers

    def sync_result(self, sync_result):
        self.data = sync_result["Properties"]["Body"]["Data"]

    def sync_err(self, err_val):
        print "EMAIL SYNC ERR",err_val.value
        if err_val.value == "ActiveSync error 135":
            print "RETRY REQUEST..."
        if isinstance(err_val.value, Exception):
            raise
        return None

    def fillDataCache(self):
        print "FILLING DATA CACHE",self.collection_id,self.info["ServerId"]
        #d = self.async.add_operation(self.async.fetch, self.collection_id, self.info["ServerId"], 4, mimeSupport=2)
        d = self.async.add_operation(self.async.fetch, self.collection_id, self.info["ServerId"], 1)
        d.addCallback(self.sync_result)
        d.addErrback(self.sync_err)
        return d

    def getBodyFile(self):
        "return a file-like object containing this message's body"
        print "GET DATA",self.info
        assert self.data != None
        return StringIO(self.data)

    def getSize(self):
        return self.info["ApplicationData"]["Body"]["EstimatedDataSize"]

    def getInternalDate(self):
        date = datetime.datetime.strptime(self.info["ApplicationData"]["DateReceived"], '%Y-%m-%dT%H:%M:%S.%fZ')
        #utc = utc.replace(tzinfo=from_zone)
        print "DATE",date
        return formatdate(time.mktime(date.timetuple()))

    def isMultipart(self):
        return False
        #return self.message.is_multipart()

    def getSubPart(self, partNo):
        print "GET PART",partNo
        return EASMessagePart(self.message.get_payload(partNo))

class EASMessage(EASMessagePart):
    implements(imap4.IMessage)

    def __init__(self, messageInfo, uid, flags, async, collection_id):
        print "Init message with uid",uid
        self.data = None
        self.collection_id = collection_id
        self.info = messageInfo
        self.async = async
        self.uid = uid
        self.flags = flags

    def getUID(self):
        return self.uid

    def getFlags(self):
        return self.flags

class IMAPServerProtocol(imap4.IMAP4Server):
    "Subclass of imap4.IMAP4Server that adds debugging."
    debug = True
    def lineReceived(self, line):
        if self.debug:
            print "CLIENT:", line
        imap4.IMAP4Server.lineReceived(self, line)

    def sendLine(self, line):
        imap4.IMAP4Server.sendLine(self, line)
        if self.debug:
            print "SERVER:", line

    def spew_body(self, part, id, msg, _w=None, _f=None):
        print "SPEW BODY"
        return imap4.IMAP4Server.spew_body(self, part, id, msg, _w, _f)

class IMAPUserAccount(object):
    implements(imap4.IAccount)
    def __init__(self, async):
        self.async = async
        self.did_provision = False

    def listResponse(self, list_result):
        global global_per_user_cache
        if self.async.username not in global_per_user_cache["mailbox"]:
            global_per_user_cache["mailbox"][self.async.username] = {}
        #acceptable_folder_types = [6, 5, 1, 3, 4, 2] # figure out what these are (EAS)
        acceptable_folder_types = [1, 2]
        for folder_id, folder_info in list_result.iteritems():
            folder_path = folder_info["DisplayName"]
            parent_id = folder_info["ParentId"]
            while int(parent_id) != 0:
                parent_info = list_result[parent_id]
                folder_path = parent_info["DisplayName"]+MAILBOXDELIMITER+folder_path
                parent_id = int(parent_info["ParentId"])

            if int(folder_info["Type"]) in acceptable_folder_types and folder_path not in global_per_user_cache["mailbox"][self.async.username]:
                global_per_user_cache["mailbox"][self.async.username][folder_path] = EASIMAPMailbox(folder_path, folder_info, self.async)
        
        return global_per_user_cache["mailbox"][self.async.username].items()

    def provision_result(self, provision_success):
        return self.listMailboxes(None, None)

    def listError(self, fail_obj):
        print "LIST ERR", fail_obj.value
        if not self.did_provision:
            print "Trying to re-provision EAS..."
            self.did_provision = True
            d = self.async.add_operation(self.async.provision)
            d.addCallback(self.provision_result)
            d.addErrback(self.listError)
            return d
        return []

    def listMailboxes(self, ref, wildcard):
        if self.async.username in global_per_user_cache["mailbox"]:
            return global_per_user_cache["mailbox"][self.async.username].items()
        d = self.async.add_operation(self.async.folder_sync)
        d.addCallback(self.listResponse)
        d.addErrback(self.listError)
        return d

    def select_callback(self, result, mbox=None):
        if mbox != None:
            return mbox
        elif isinstance(result, EASIMAPMailbox):
            d = result.fill_data_cache()
            d.addCallback(self.select_callback, result)
            return d
        else:
            raise Exception("Unexpected value "+str(result))

    def select(self, path, rw=True):
        "return an object implementing IMailbox for the given path"
        mbox_or_deferred = self._getMailbox(path)
        if isinstance(mbox_or_deferred, EASIMAPMailbox):
            d = mbox_or_deferred.fill_data_cache()
            d.addCallback(self.select_callback, mbox_or_deferred)
            return d
        mbox_deferred.addCallback(self.select_callback)
        return mbox_deferred

    def _getMailbox_callback(self, mboxlist, path, create=False):
        return self._getMailbox(path, create)

    def _getMailbox(self, path, create=False):
        """
        Helper function to get a mailbox object at the given
        path, optionally creating it if it doesn't already exist.
        """
        if create:
            raise imap4.MailboxException("Create not yet supported.")

        if self.async.username in global_per_user_cache["mailbox"]:
            if path in global_per_user_cache["mailbox"][self.async.username]:
                return global_per_user_cache["mailbox"][self.async.username][path]
            for mbpath in global_per_user_cache["mailbox"][self.async.username].keys():
                # case insensitive search
                if path.lower() == mbpath.lower():
                    return global_per_user_cache["mailbox"][self.async.username][mbpath]
        d = self.async.add_operation(self.async.folder_sync)
        d.addCallback(self.listResponse)
        d.addCallback(self._getMailbox_callback, path, create)
        d.addErrback(self.listError)
        return d

    def create(self, path):
        raise imap4.MailboxException("Create not yet supported.")
        "create a mailbox at path and return it"
        #self._getMailbox(path, create=True)

    def delete(self, path):
        "delete the mailbox at path"
        raise imap4.MailboxException("Delete not yet supported.")

    def rename(self, oldname, newname):
        "rename a mailbox"
        raise imap4.MailboxException("Rename not yet supported.")

    def isSubscribed(self, path):
        "return a true value if user is subscribed to the mailbox"
        return True

    def subscribe(self, path):
        "mark a mailbox as subscribed"
        pass

    def unsubscribe(self, path):
        "mark a mailbox as unsubscribed"
        pass


class EASCredentialsChecker(object):
    implements(checkers.ICredentialsChecker)
    credentialInterfaces = (credentials.IUsernamePassword, )

    def __init__(self, domain, server, device_id=None):
        self.async = None
        self.domain = domain
        self.server = server
        self.device_id = device_id

    def requestAvatarId(self, credentials):
        self.async = activesync.ActiveSync(self.domain, credentials.username, 
            credentials.password, self.server, True, device_id=self.device_id, verbose=False)
        d = self.async.add_operation(self.async.get_options)
        d.addCallback(self.option_result, credentials.username)
        d.addErrback(self.option_err)
        return d

    def option_result(self, result, username):
        # the entire async object is the avatar ID
        return self.async

    def option_err(self, err):
        raise credError.UnauthorizedLogin("No such user")


class MailUserRealm(object):
    implements(portal.IRealm)
    avatarInterfaces = {
        imap4.IAccount: IMAPUserAccount,
    }
    def requestAvatar(self, avatarId, mind, *interfaces):
        for requestedInterface in interfaces:
            if self.avatarInterfaces.has_key(requestedInterface):
                # return an instance of the correct class
                avatar = self.avatarInterfaces[requestedInterface](avatarId)
                # null logout function: take no arguments and do nothing
                logout = lambda: None
                return defer.succeed((requestedInterface, avatar, logout))
        # none of the requested interfaces was supported
        raise KeyError("None of the requested interfaces is supported")

class IMAPFactory(protocol.Factory):
    protocol = IMAPServerProtocol
    portal = None # placeholder
    def buildProtocol(self, address):
        p = self.protocol()
        p.portal = self.portal
        p.factory = self
        return p

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print "Usage: <domain> <server hostname> [device id]"
        sys.exit(1)

    try: device_id = sys.argv[3]
    except: device_id = None

    eas_portal = portal.Portal(MailUserRealm())
    eas_portal.registerChecker(EASCredentialsChecker(sys.argv[1], sys.argv[2], device_id=device_id))

    factory = IMAPFactory()
    factory.portal = eas_portal
    reactor.listenTCP(3143, factory)

    reactor.run()