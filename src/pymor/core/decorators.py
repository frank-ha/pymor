# -*- coding: utf-8 -*-
"""
Created on Fri Nov  2 10:12:55 2012

@author: r_milk01
"""

"""Collection of function/class based decorators."""

import functools
import types
import inspect
import logging
import contracts
import copy

def _is_decorated(func):
    return 'decorated' in dir(func)


class DecoratorBase(object):
    """A base for all decorators that does the common automagic"""
    def __init__(self, func):
        functools.wraps(func)(self)
        func.decorated = self
        self.func = func
        assert _is_decorated(func)

    def __get__(self, obj, ownerClass=None):
        # Return a wrapper that binds self as a method of obj (!)
        self.obj = obj
        return types.MethodType(self, obj)

class DecoratorWithArgsBase(object):
    """A base for all decorators with args that sadly can do little common automagic"""
    def mark(self, func):
        functools.wraps(func)
        func.decorated = self

    def __get__(self, obj, ownerClass=None):
        # Return a wrapper that binds self as a method of obj (!)
        self.obj = obj
        return types.MethodType(self, obj)


class Deprecated(DecoratorBase):
    """This is a decorator which can be used to mark functions
    as deprecated. It will result in a warning being emitted
    when the function is used.
    """

    def __init__(self, alt='no alternative given'):
        self._alt = alt

    def __call__(self, func):
        func.decorated = self
        @functools.wraps(func)
        def new_func(*args, **kwargs):
            frame = inspect.currentframe().f_back
            msg = "DeprecationWarning. Call to deprecated function %s in %s:%s\nUse %s instead" % (
                            func.__name__, frame.f_code.co_filename,
                            frame.f_code.co_firstlineno, self._alt)
            logging.warning(msg)
            return func(*args, **kwargs)
        return new_func

def contract(*arg, **kwargs):
    '''
        Decorator for adding contracts to functions.

        It is smart enough to support functions with variable number of
        arguments and keyword arguments.

        There are three ways to specify the contracts. In order of precedence:

        - As arguments to this decorator. For example: ::

              @contract(a='int,>0',b='list[N],N>0',returns='list[N]')
              def my_function(a, b):
                  # ...
                  pass

        - As annotations (supported only in Python 3): ::

              @contract
              def my_function(a:'int,>0', b:'list[N],N>0') -> 'list[N]':
                  # ...
                  pass

        - Using ``:type:`` and ``:rtype:`` tags in the function's docstring: ::

              @contract
              def my_function(a, b):
                  """ Function description.
                      :type a: int,>0
                      :type b: list[N],N>0
                      :rtype: list[N]
                  """
                  pass

        **Signature and docstrings**: The signature of the decorated
        function is conserved. By default, the docstring is modified
        by adding ``:type:`` and ``:rtype:`` definitions. To avoid that,
        pass ``modify_docstring=False`` as a parameter.


        **Contracts evaluation**: Note that all contracts for the arguments
        and the return values
        are evaluated in the same context. This make it possible to use
        common variables in the contract expression. For example, in the
        example above, the return value is constrained to be a list of the same
        length (``N``) as the parameter ``b``.

        **Using docstrings** Note that, by convention, those annotations must
        be parseable as RestructuredText. This is relevant if you are using
        Sphinx.
        If the contract string has special RST characters in it, like ``*``,
        you can include it in double ticks. |pycontracts| will remove
        the double ticks before interpreting the string.

        For example, the two annotations in this docstring are equivalent
        for |pycontracts|, but the latter is better for Sphinx: ::

              """ My function

                  :param a: First parameter
                  :type a: list(tuple(str,*))

                  :param b: First parameter
                  :type b: ``list(tuple(str,*))``
              """

        :raise: ContractException, if arguments are not coherent
        :raise: ContractSyntaxError
    '''

    # this bit tags function as decorated
    def tag_and_decorate(function, **kwargs):
        @functools.wraps(function)
        def __functools_wrap(function, **kwargs):
            new_f = contracts.main.contracts_decorate(function, **kwargs)
            cargs = copy.deepcopy(kwargs)
            new_f.contract_kwargs = cargs or dict()
            new_f.decorated = 'contract'
            return new_f
        return __functools_wrap(function, **kwargs)

    # OK, this is black magic. You are not expected to understand this.
    if arg:
        if isinstance(arg[0], types.FunctionType):
            # We were called without parameters
            function = arg[0]
            if contracts.all_disabled():
                return function
            try:
                return tag_and_decorate(function, **kwargs)
            except contracts.ContractSyntaxError as e:
                # Erase the stack
                raise e
                raise contracts.ContractSyntaxError(e.error, e.where)
        else:
            msg = ('I expect that  contracts() is called with '
                    'only keyword arguments (passed: %r)' % arg)
            raise contracts.ContractException(msg)
    else:
        # We were called *with* parameters.
        if contracts.all_disabled():
            def tmp_wrap(function):
                return function
        else:
            def tmp_wrap(function):
                try:
                    return tag_and_decorate(function, **kwargs)
                except contracts.ContractSyntaxError as e:
                    # Erase the stack
                    raise contracts.ContractSyntaxError(e.error, e.where)
        return tmp_wrap

# alias this so we need no contracts import outside this module
contracts_decorate = contracts.main.contracts_decorate

def contains_contract(string):
    try:
        contracts.parse_contract_string(string)
        return True
    except:
        return False
