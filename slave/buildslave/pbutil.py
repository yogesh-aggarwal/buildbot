
"""Base classes handy for use with PB clients.
"""

from twisted.spread import pb

from twisted.spread.pb import PBClientFactory
from twisted.internet import protocol, reactor
from twisted.python import log

class ReconnectingPBClientFactory(PBClientFactory,
                                  protocol.ReconnectingClientFactory):
    """Reconnecting client factory for PB brokers.

    Like PBClientFactory, but if the connection fails or is lost, the factory
    will attempt to reconnect.

    Instead of using f.getRootObject (which gives a Deferred that can only
    be fired once), override the gotRootObject method.

    Instead of using the newcred f.login (which is also one-shot), call
    f.startLogin() with the credentials and client, and override the
    gotPerspective method.

    gotRootObject and gotPerspective will be called each time the object is
    received (once per successful connection attempt). You will probably want
    to use obj.notifyOnDisconnect to find out when the connection is lost.

    If an authorization error occurs, failedToGetPerspective() will be
    invoked.

    To use me, subclass, then hand an instance to a connector (like
    TCPClient).
    """

    # hung connections wait for a relatively long time, since a busy master may
    # take a while to get back to us.
    hungConnectionTimer = None
    HUNG_CONNECTION_TIMEOUT = 120

    def clientConnectionFailed(self, connector, reason):
        PBClientFactory.clientConnectionFailed(self, connector, reason)
        if self.continueTrying:
            self.connector = connector
            self.retry()

    def clientConnectionLost(self, connector, reason):
        PBClientFactory.clientConnectionLost(self, connector, reason,
                                             reconnecting=True)
        RCF = protocol.ReconnectingClientFactory
        RCF.clientConnectionLost(self, connector, reason)

    def startedConnecting(self, connector):
        self.startHungConnectionTimer(connector)

    def clientConnectionMade(self, broker):
        self.resetDelay()
        PBClientFactory.clientConnectionMade(self, broker)
        self.doLogin(self._root)
        self.gotRootObject(self._root)

    # newcred methods

    def login(self, *args):
        raise RuntimeError, "login is one-shot: use startLogin instead"

    def startLogin(self, credentials, client=None):
        self._credentials = credentials
        self._client = client

    def doLogin(self, root):
        # newcred login()
        d = self._cbSendUsername(root, self._credentials.username,
                                 self._credentials.password, self._client)
        d.addCallbacks(self.gotPerspective, self.failedToGetPerspective)

    # timer for hung connections

    def startHungConnectionTimer(self, connector):
        self.stopHungConnectionTimer()
        def hungConnection():
            log.msg("connection attempt timed out (is the port number correct?)")
            self.hungConnectionTimer = None
            connector.disconnect()
            # (this will trigger the retry)
        self.hungConnectionTimer = reactor.callLater(self.HUNG_CONNECTION_TIMEOUT, hungConnection)

    def stopHungConnectionTimer(self):
        if self.hungConnectionTimer:
            self.hungConnectionTimer.cancel()
        self.hungConnectionTimer = None

    # methods to override

    def gotPerspective(self, perspective):
        """The remote avatar or perspective (obtained each time this factory
        connects) is now available."""
        self.stopHungConnectionTimer()

    def gotRootObject(self, root):
        """The remote root object (obtained each time this factory connects)
        is now available. This method will be called each time the connection
        is established and the object reference is retrieved."""
        self.stopHungConnectionTimer()

    def failedToGetPerspective(self, why):
        """The login process failed, most likely because of an authorization
        failure (bad password), but it is also possible that we lost the new
        connection before we managed to send our credentials.
        """
        log.msg("ReconnectingPBClientFactory.failedToGetPerspective")
        self.stopHungConnectionTimer()
        if why.check(pb.PBConnectionLost):
            log.msg("we lost the brand-new connection")
            # retrying might help here, let clientConnectionLost decide
            return
        # probably authorization
        self.stopTrying() # logging in harder won't help
        log.err(why)
        reactor.stop()
