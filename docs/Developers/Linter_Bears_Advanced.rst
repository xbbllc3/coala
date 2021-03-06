Linter Bears - Advanced Feature Reference
=========================================

Often linters are no easy tools. To squeeze out the last bit of functionality
and efficiency, ``@linter`` provides some advanced features ready for use.

Supplying Configuration Files with ``generate_config``
------------------------------------------------------

Sometimes tools require a configuration file to run. ``@linter`` supports that
easily by overriding ``generate_config()``.

::

    @linter(executable='...')
    class MyBear:
        @staticmethod
        def generate_config(filename, file):
            config_file = ("value1 = 1\n"
                           "value2 = 2")
            return config_file

The string returned by this method is written into a temporary file before
invoking ``create_arguments()``.

The path of the temporary configuration file can be accessed inside
``create_arguments()`` via the ``config_file`` parameter:

::

    @linter(executable='...')
    class MyBear:
        @staticmethod
        def generate_config(filename, file):
            config_file = ("value1 = 1\n"
                           "value2 = 2")
            return config_file

        @staticmethod
        def create_arguments(filename, file, config_file):
            return "--use-config", config_file

If you return ``None``, no configuration file is generated. A common case
where to explicitly return ``None`` is when you want to expose a setting
for the user to use his own tool-specific config. In case the user specifies
such a config file, we can avoid generating one again with ``generate_config``
to reduce I/O load.

::

    @linter(executable='...')
    class MyBear:
        @staticmethod
        def generate_config(filename, file,
                            user_config: str='',
                            setting_a: bool=False):
            if user_config:
                return None
            else:
                return 'A={}'.format(setting_a)

        def create_arguments(filename, file, config_file,
                             user_config: str=''):
            return (filename, '--use-config',
                    user_config if user_config else config_file)

.. note::

    By default, no configuration file is generated.

Custom Processing Functions with ``process_output``
---------------------------------------------------

Inside ``@linter`` only a few output formats are supported. And they can't be
combined for different output streams. To specify an own output
parsing/processing behaviour, ``process_output`` can be overridden.

::

    @linter(executable='my_tool')
    class MyBear:
        def process_output(self, output, filename, file):
            pass

The ``output`` variable contains the string output from the executable.
Depending on how you use the ``use_stdout`` and ``use_stderr`` parameters from
``@linter``, ``output`` can contain either a tuple or a plain string: If
``use_stdout`` and ``use_stderr`` are both ``True``, a tuple is placed with
``(stdout, stderr)``. If only one of them is ``True``, a string is passed
(containing the output stream chosen).

Inside ``process_output`` you need to yield results according to the executable
output. It is also possible to combine the built-in capabilities. There are
several functions accessible with the naming scheme
``process_output_<output-format>``.

- ``process_output_regex``: Extracts results using a regex.

  ::

      @linter(executable='my_tool',
              use_stdout=False,
              use_stderr=True)
      class MyBear:
          # Assuming the tool puts some issue messages into stderr.
          def process_output(self, output, filename, file):
              # output is a string, as we activated just ``use_stderr``
              map = {'info': RESULT_SEVERITY.INFO,
                     'warn': RESULT_SEVERITY.NORMAL,
                     'error': RESULT_SEVERITY.MAJOR}
              regex = "(?P<line>\d+):(?P<message>(?P<severity>[WEI]).*)"
              yield from self.process_output_regex(stderr,
                                                   filename,
                                                   file,
                                                   regex,
                                                   map)

  A static message to use for results instead of grabbing it from the executable
  output (via the ``message`` named regex group) can also be provided using the
  ``result_message`` parameter.

- ``process_output_corrected``: Extracts results (with patches) by using a
  corrected version of the file processed.

  ::

    @linter(executable='my_tool',
            use_stdout=True,
            use_stderr=False)
    class MyBear:
        # Assuming the tool puts a corrected version of the file into stdout.
        def process_output(self, output, filename, file):
            # output is a string, as we activated just ``use_stdout``
            yield from self.process_output_corrected(
                                stdout,
                                filename,
                                file,
                                diff_severity=RESULT_SEVERITY.NORMAL,
                                diff_distance=2)

  The ``diff_distance`` parameter takes the number of unchanged lines
  allowed in between two changed lines so they get yielded as a single diff.
  If ``-1`` is given, every change will be yielded as an own diff.

- ``process_output_unified_diff``: Extracts results (with patches) by processing
  a unified diff.

  ::

      @linter(executable='my_tool',
              use_stdout=True,
              use_stderr=True)
      class MyBear:
          # Assuming the tool puts a unified diff into stdout
          # and additional issue messages (that can't be fixed automatically)
          # into stderr, let's combine both streams!
          def process_output(self, output, filename, file):
              # output is now a tuple, as we activated both, ``use_stdout`` and
              # ``use_stderr``.
              stdout, stderr = output
              yield from self.process_output_unified_diff(stdout,
                                                          filename,
                                                          file)
              regex = "(?P<message>.*)"
              yield from self.process_output_regex(stderr,
                                                   filename,
                                                   file,
                                                   regex)


JSON output is also very common:

::

    @linter(executable='my_tool')
    class MyBear:
        def process_output(self, output, filename, file):
            for issue in json.loads(output):
                yield Result.from_values(origin=self,
                                         message=issue["message"],
                                         file=filename)

Additional Prerequisite Check
-----------------------------

``@linter`` supports doing an additional executable check before running the
bear, together with the normal one (checking if the executable exists). For
example, this is useful to test for the existence of external modules (like
Java modules).

To enable this additional check with your commands, use the
``prerequisite_check_command`` parameter of ``@linter``.

::

    @linter(executable='...'
            prerequisite_check_command=('python3', '-c', 'import my_module'))
    class MyBear:
        pass

If the default error message does not suit you, you can also supply
``prerequisite_check_fail_message`` together with
``prerequisite_check_command``.

::

    @linter(executable='...'
            prerequisite_check_command=('python3', '-c', 'import my_module'),
            prerequisite_check_fail_message='my_module does not exist.')
    class MyBear:
        pass
