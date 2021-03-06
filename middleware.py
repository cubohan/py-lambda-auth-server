#!/usr/bin/python

import abc
import inspect

from custom_errors import CustomError, AuthError, ImproperErrorBundleDump, AbstractMiddlewareError
from utils import classonlymethod, RequestOp
from authorizers import Authenticator, SafeMethodOnlyAuthorizer, APIAuthorizer
from settings import SAFE_CODES, AUTH
from router import route

class AuthMiddleWare(object):
    """
    Abstract Auth Middleware for intercepting every request for auth 
        before forwarding to API backend
    """
    _metaclass_ = abc.ABCMeta # is an Abstract Base Class

    # format and keys in which errors will be raised from this class
    # @middleware_stack: dump of the current stack (depth) of middlewares executed
    # @layer: represents the AuthMiddleware from which the error was raised
    # @authorizer: the authorizer class which failed
    # @request_dump: represents the request object for ambient information
    ERROR_BUNDLE_KEYS = ["middleware_stack", "layer", "authorizer_error", "request_dump"]

    # All the auth classes against which user is authorized before delegation to
    #   subsequent layers
    AUTH_CLASSES =  []
    
    @classonlymethod
    def process_request(cls, request=None, response=None):
        """
        This static method processes request
        
        It processes the request in the below fixed order and the derived functionality
            completely depends on individual implementations of the child classes
        
        @param: cls: reference to child-class which calls this method
            can only be called on a NON-ABSTRACT class!
        @param: request: The request DICT object
        @param: response: The response DICT object
        """
        # adding/appending class to middleware stack of current request for tracking purposes
        RequestOp.appendParam(request, "middleware_stack", cls)

        if inspect.isabstract(cls): # raisisng error if caller class is an abstract class
            raise AbstractMiddlewareError(AbstractMiddlewareError.MSG_ABS_MIDDLEWARE_ERROR, 
                CustomError.bundle(cls.ERROR_BUNDLE_KEYS, request.middleware_stack, cls, None, request))
        if not hasattr(cls, '_instance'):
            setattr(cls, '_instance', None) # static instance of caller class
        if not cls._instance:
            cls._instance = cls()
            cls._instance._init()
        
        # authorize current request, let any errors propogate higher without catching
        cls._instance.authorize(request) 
        
        cls._instance.process(request, response) # process request object on current layer
        return cls._instance.delegate(request, response)
        
    def authorize(self, request):
        """
        To check if this use is authorized to penetrate the current middleware
        @param: request: The request object
        """
        for authorizer in self._get_authorizers():
            authorized = authorizer.authorize(request)
            if not authorized[0] in SAFE_CODES:
                    raise AuthError(AuthError.MSG_AUTH_FAILED, 
                        CustomError.bundle(self.__class__.ERROR_BUNDLE_KEYS, request['middleware_stack'], self.__class__, authorized, request))

    @abc.abstractmethod
    def process(self, request, response):
        """
        To further process the request object at middleware layer
        @param: request: The request object
        @param: response: The response DICT object
        """
        return

    @abc.abstractmethod
    def delegate(self, request, response):
        """
        To pass the request to succeeding layer and fetch the response
        @param: request: The request object
        @param: response: The response DICT object
        @return: respone: The response generated by subsequent layers to be returned to client
        """
        return

    def _init(self):
        """Inits authorizer classes with instances"""
        for ii, _auth in enumerate(self.AUTH_CLASSES):
            self.AUTH_CLASSES[ii] = _auth()

    def _get_authorizers(self):
        """wrapper method for fetching authorizers"""
        return self.AUTH_CLASSES

    def __getattr__(self, name):
        try:
            return self.__dict[name]
        except KeyError:
            msg = "'{0}' object has no attribute '{1}'"
            raise AttributeError(msg.format(type(self).__name__, name))

    def __setattr__(self, name, value):
        self.__dict[name] = value


class StackedAuthMiddleWare(AuthMiddleWare):
    """
    Abstract Stacked Auth Middleware for a convinient way to stack multiple Middlewares
        in succession
    For stacks further down below, any previously used authenticators should be removed
        to avoid redundacies
    """
    _metaclass_ = abc.ABCMeta # is an Abstract Base Class

    # list of stacked middlewares all of which will be processed in the delegate method
    STACKED_MIDDLEWARES = [] 

    def delegate(self, request, response):
        """
        From the list of stacked middlewares, only the last response is returned
            this default behaviour may be changed by overriding in a child class
        """
        for s_mw in self._get_stacked_middlewares():
            response = s_mw.process_request(request, response)
        return response # return last fetched response

    def _get_stacked_middlewares(self): 
        """wrapper method for fetching stacked middlewares"""
        return self.STACKED_MIDDLEWARES


class ViewAuthMiddleWare(AuthMiddleWare):
    # @view represents the requested view for which access was denied 
    AUTH_CLASSES =  [SafeMethodOnlyAuthorizer, APIAuthorizer]
    
    def process(self, request, response):
        return

    def delegate(self, request, response):
        return route(request, response)


class IdentityAuthMiddleWare(StackedAuthMiddleWare):
    
    AUTH_CLASSES = [Authenticator]
    STACKED_MIDDLEWARES = [ViewAuthMiddleWare]

    def process(self, request, response):
        return

    def delegate(self, request, response):
        if Authenticator.is_requesting_authentication(request):
            # including token to response
            response[AUTH['TOKEN_HEADER']] = request[AUTH['TOKEN_HEADER']][1]
            return response
        return super(IdentityAuthMiddleWare, self).delegate(request, response)

