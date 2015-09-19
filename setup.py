from distutils.core import setup


def pip_requirements(extra=None):
    if extra is None:
        path = "requirements.txt"
    else:
        path = "requirements.{}.txt".format(extra)
    with open(path) as f:
        return f.readlines()


setup(
    name="aioserver",
    version="0.0.1",
    packages=[
        "aioserver",
    ],
    install_requires=pip_requirements(),
    entry_points={
        'console_scripts': [
            'aioserver = aioserver.cli:main',
        ],
    }
)
