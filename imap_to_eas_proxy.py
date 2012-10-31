from twisted.mail import imap4, maildir
from twisted.internet import reactor, defer, protocol
from twisted.cred import portal, checkers, credentials
from twisted.cred import error as credError
from zope.interface import implements
import time, os, random, sys
from twisted.python import log

from eas_client import *

from cStringIO import StringIO
import email


MAILBOXDELIMITER = "."

log.startLogging(sys.stdout)

#ChandlerMaildir will map directly to a Collection Name
class ChandlerMaildir(object):
    
    def __init__(self, collectionName):
        
        #XXX: collectionName redirections Inbox-> In
        # Sent -> Out
        # Trash
        print "passed collectionName: ", collectionName
        
        if collectionName.lower() == 'inbox':
            collectionName = 'In'
            
        self.collectionName = collectionName
        
        #Instead of list this should be a collection of MailMessage UUIDS
        self.list = [] #UUID Strings
        
        #Cache to undo delete
        self.deleted = {}
        
        #initializeMaildir(path)
        
        # Get sidebar
        sidebar = schema.ns('osaf.app', view).sidebarCollection
        self.collection = None
        for coll in sidebar:
            if coll.displayName == collectionName:
                self.collection = coll
                break
        
        # Create a collection if non-existent
        if self.collection is None:
            self.collection = pim.SmartCollection(itsView=view,
                displayName=collectionName).setup( )
            sidebar.add(self.collection)
                
        for item in self.collection:
            if isinstance(item, pim.mail.MailMessageMixin):
                self.list.append(str(item.itsUUID))
                
        # for name in ('cur', 'new'):
        #    for file in os.listdir(os.path.join(path, name)):
        #        self.list.append((file, os.path.join(path, name, file)))
        # self.list.sort()
        # self.list = [e[1] for e in self.list]

    def appendMessage(self, msgText):
        raise imap4.MailboxException("ChandlerMaildir.appendMessage not supported")
        #XXX create a Chandler MailMessage for the given txt and add to the current collection and out collection
    
        
        print "msgText passed to append is of type %s " % type(msgText)
        
        if hasattr(msgText, "read"):       
            raise imap4.MailboxException("Warning read() not yet supported")
            
        #XXX this logic could be moved to deferreds to make async. Need to think about this more
                
        mailMessage = message.messageTextToKind(view, msgText)   
        self.collection.add(mailMessage)
        
        self.list.append(str(mailMessage.itsUUID)) 
         
        view.commit()
        
        #The value returned is ignored by the callback 
        return defer.succeed(None)
            
    def deleteMessage(self, index):
        """Delete a particular message.

        This must not change the number of messages in this mailbox.  Further
        requests for the size of deleted messages should return 0.  Further
        requests for the message itself may raise an exception.

        @type index: C{int}
        @param index: The number of the message to delete.
        """
        raise imap4.MailboxException("ChandlerMaildir.deleteMessage not supported")
        
        """Delete a message

        This only moves a message to the .Trash/ subfolder,
        so it can be undeleted by an administrator.
        """
        #trashFile = os.path.join(
        #    self.path, '.Trash', 'cur', os.path.basename(self.list[i])
        #)
        #os.rename(self.list[i], trashFile)
        #self.deleted[self.list[i]] = trashFile
        #self.list[i] = 0

     
    def undeleteMessages(self):
        """Undelete any messages possible.

        If a message can be deleted it, it should return it its original
        position in the message sequence and retain the same UIDL.
        """

        raise imap4.MailboxException("ChandlerMaildir.undeleteMessages not supported")
        """Undelete any deleted messages it is possible to undelete

        This moves any messages from .Trash/ subfolder back to their
        original position, and empties out the deleted dictionary.
        """
        #for (real, trash) in self.deleted.items():
        #    try:
        #        os.rename(trash, real)
        #    except OSError, (err, estr):
        #        import errno
        #        # If the file has been deleted from disk, oh well!
        #        if err != errno.ENOENT:
        #            raise
        #        # This is a pass
        #    else:
        #        try:
        #            self.list[self.list.index(0)] = real
        #        except ValueError:
        #            self.list.append(real)
        #self.deleted.clear()
        
    def getMessage(self, index):
        """Return an open file-pointer to a message
        """
        uuid = UUID(self.list[i])
        item = view[uuid]
        return item.rfc2282Message.getInputStream()
        
        # return open(self.list[i])

    
    def getUidl(self, index):
        """Return a unique identifier for a message

        This is done using the basename of the filename.
        It is globally unique because this is how Maildirs are designed.
        """
        return self.list[i]
        
        # Returning the actual filename is a mistake.  Hash it.
        #XXX this just returns the UUID of the MailMessage Item
        #base = os.path.basename(self.list[i])
        #return md5.md5(base).hexdigest()

    def _getRfc2822Message(self, uuid):
        uuid = UUID(uuid)
        item = view[uuid]
        return binaryToData(item.rfc2822Message)
    
    def listMessages(self, index=None):
        """Return a list of lengths of all files in new/ and cur/
        """
        
        if index is None:
            ret = []
            for uuid in self.list:
                if uuid:
                    ret.append(len(self._getRfc2822Message(uuid)))
                else:
                    ret.append(0)
            return ret
        else:
            uuid = self.list[index]
            return uuid and len(self._getRfc2822Message(uuid)) or 0


    
    
    def sync(self):
        """Perform checkpointing.

        This method will be called to indicate the mailbox should attempt to
        clean up any remaining deleted messages.
        """
        pass
        
    def __iter__(self):
        "iterates through the full paths of all messages in the maildir"
        return iter(self.list)

    def __len__(self):
        return len(self.list)

    def __getitem__(self, i):
        return self.list[i]


class IMAPMailbox(object):
    implements(imap4.IMailbox)

    def __init__(self, path, info, async):
        self.collectionName = path.split(os.sep)[-1]
        print "Creating maildir", self.collectionName
        self.async = async
        self.folderinfo = info
        self.metadata = {}
        self.listeners = []
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
        d = self.async.sync(self.folderinfo["ServerId"])
        d.addCallback(self.sync_result)
        d.addErrback(self.sync_err)
        return d

    def getMessageCount(self):
        print "Getting message count", self.collectionName, (self.dataCache == None)
        if self.dataCache == None:
            print "Calling fill_data_cache"
            self.fill_data_cache()
            return 0
        return len(self.dataCache)

    def getRecentCount(self):
        return 0

    def getUnseenCount(self):
        print "Getting unseencount", self.collectionName

        if self.dataCache == None:
            print "Calling fill_data_cache"
            self.fill_data_cache()
            return 0

        unseencount = 0
        for msg in self.dataCache.values():
            if msg["ApplicationData"]["Read"] != "1":
                unseencount += 1
        return unseencount

    def isWriteable(self):
        return True

    def getUIDValidity(self):
        return self.metadata['uidvalidity']

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
        print "SYNC RESULT",sync_result
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

    def sync_err(self, err_val):
        print "SYNC ERR",err_val
        return None


    def fetch_callback(self, ignore, messages, uid):
        return self.fetch(messages, uid)
    def fetch(self, messages, uid):
        print "FETCH",messages,uid
        assert uid == 1

        if self.dataCache == None:
            d = self.fill_data_cache()
            d.addCallback(self.fetch_callback, messages, uid)
            return d

        messagesToFetch = self._uidMessageSetToSeqDict(messages)
        print "TO FETCH",messagesToFetch
        fetch_res = []
        for seq, server_id in messagesToFetch.items():
            uid = self.metadata["uids"][server_id]
            flags = self.metadata['flags'][uid]
            fetch_res.append((seq, EASMessage(self.dataCache[server_id], uid, flags)))
        print "Fetch res",fetch_res
        return fetch_res

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
        #XXX: Just use the UUID's
        for filename in self.maildir:
            uid = self.metadata['uids'].get(os.path.basename(filename))
            if r"\Deleted" in self.metadata['flags'].get(uid, []):
                self.maildir.deleteMessage(filename)
                # you could also throw away the metadata here
                removed.append(uid)
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
        print "GET HEADERS"
        """
        Return a dict mapping header name to header value. If *names
        is empty, match all headers; if negate is true, return only
        headers _not_ listed in *names.
        """
        if not names: names = self.message.keys()
        headers = {}
        if negate:
            for header in self.message.keys():
                if header.upper() not in names:
                    headers[header.lower()] = self.message.get(header, '')
        else:
            for name in names:
                headers[name.lower()] = self.message.get(name, '')
        return headers

    def getBodyFile(self):
        "return a file-like object containing this message's body"
        print "GET DATA"
        bodyData = str(self.message.get_payload())
        return StringIO(bodyData)

    def getSize(self):
        return len(self.data)

    def getInternalDate(self):
        return self.message.get('Date', '')

    def isMultipart(self):
        return self.message.is_multipart()

    def getSubPart(self, partNo):
        return EASMessagePart(self.message.get_payload(partNo))

class EASMessage(EASMessagePart):
    implements(imap4.IMessage)

    def __init__(self, messageInfo, uid, flags):
        print "Init message with uid",uid
        self.data = None
        self.info = messageInfo
        self.message = None #email.message_from_string(self.data)
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

class IMAPUserAccount(object):
    implements(imap4.IAccount)
    def __init__(self, async):
        self.async = async
        self.did_provision = False
        self.mailboxCache = None

    def listResponse(self, list_result):
        if self.mailboxCache == None: self.mailboxCache = {}
        for folder_id, folder_info in list_result.iteritems():
            folder_path = folder_info["DisplayName"]
            parent_id = folder_info["ParentId"]
            while int(parent_id) != 0:
                parent_info = list_result[parent_id]
                folder_path = parent_info["DisplayName"]+MAILBOXDELIMITER+folder_path
                parent_id = int(parent_info["ParentId"])
        
            self.mailboxCache[folder_path] = IMAPMailbox(folder_path, folder_info, self.async)
        
        return self.mailboxCache.items()

    def provision_result(self, provision_success):
        return self.listMailboxes(None, None)

    def listError(self, fail_obj):
        print "LIST ERR", fail_obj.value
        if not self.did_provision:
            print "Trying to re-provision EAS..."
            self.did_provision = True
            d = self.async.provision()
            d.addCallback(self.provision_result)
            d.addErrback(self.listError)
            return d
        return []

    def listMailboxes(self, ref, wildcard):
        if self.mailboxCache != None:
            return self.mailboxCache.items()
        d = self.async.folder_sync()
        d.addCallback(self.listResponse)
        d.addErrback(self.listError)
        return d

    def select(self, path, rw=True):
        "return an object implementing IMailbox for the given path"
        return self._getMailbox(path)

    def _getMailbox_callback(self, mboxlist, path, create=False):
        return self._getMailbox(path, create)

    def _getMailbox(self, path, create=False):
        """
        Helper function to get a mailbox object at the given
        path, optionally creating it if it doesn't already exist.
        """
        if create:
            raise imap4.MailboxException("Create not yet supported.")

        if self.mailboxCache != None:
            if path in self.mailboxCache:
                return self.mailboxCache[path]
            for mbpath in self.mailboxCache.keys():
                # case insensitive search
                if path.lower() == mbpath.lower():
                    return self.mailboxCache[mbpath]
        d = self.async.folder_sync()
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
        d = self.async.get_options()
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