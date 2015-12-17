# Settings are always a tuple, where the first two members 
# are 'name' and 'title'
# The third member can be either:
#   1.  a string containing pipe delimited pulldown options
#   2.  'CB' for a checkbox, followed by a boolean member for the default, and the flag that is used if true
#   3.  'STR' for a single-line string value, followed by the string default
#   4.  'EDIT' for a multi-line string value, followed by the string default

tabs={
    'Compile':[
        ('BUILD_OPT','Optimization','-O0|-O1|-O2|-O3','-O2'),
        ('COMPILE_WARN','Warnings','Default|None (-w)|All (-Wall)','Default'),
        ('COMPILE_PEDANTIC','Pedantic','CB',False,'-pedantic-errors'),
        ('COMPILE_WARNERR','Warning as errors','CB',False,'-Werror'),
        ('COMPILE_CPP11','Standard','Default|-std=c++0x|-std=c++11','-std=c++11')
    ],
    'Link':[
    ],
    'Advanced':[
        ('COMPILE_CUSTOM','Custom Compile Flags','EDIT',''),
        ('LINK_CUSTOM','Custom Link Flags','EDIT','')
    ]
}
