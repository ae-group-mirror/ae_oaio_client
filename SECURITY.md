<!-- THIS FILE IS EXCLUSIVELY MAINTAINED by the project aedev.project_tpls v0.3.78 -->
# using this package securely

## reporting security issues

to report a security issue, please email [aecker2@gmail.com](mailto:aecker2@gmail.com).

## dynamic execution of code blocks and evaluable expressions

the Python language provides powerful functions to execute code blocks and to evaluate expressions, which could be
mis-used to execute inject and execute malicious code snippets. caught has to be taken especially if these functions are
interpreting command line arguments, config file options, or user input.
