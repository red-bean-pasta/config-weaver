
class NonFatalError(Exception):
    pass


class UserNotFoundError(NonFatalError):
    pass


class NoOutboundDefinedError(NonFatalError):
    pass


class WrongEncryptionKeyError(NonFatalError):
    pass


class ConfigurationError(Exception):
    pass


class UnsafeBindingError(Exception):
    pass