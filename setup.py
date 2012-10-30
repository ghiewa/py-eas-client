from distutils.core import setup
import os

setup(
    name = 'eas_client',
    version = '1.00',
    description = 'EAS client in python, based on twisted.',

    author = 'Braden Thomas',
    author_email =  'drspringfield@gmail.com',
    packages = ["eas_client"],
    package_dir = {'': 'src'}
)
