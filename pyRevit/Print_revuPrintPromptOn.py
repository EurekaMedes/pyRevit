'''
Copyright (c) 2014-2016 Ehsan Iran-Nejad
Python scripts for Autodesk Revit

This file is part of pyRevit repository at https://github.com/eirannejad/pyRevit

pyRevit is a free set of scripts for Autodesk Revit: you can redistribute it and/or modify
it under the terms of the GNU General Public License version 3, as published by
the Free Software Foundation.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

See this link for a copy of the GNU General Public License protecting this package.
https://github.com/eirannejad/pyRevit/blob/master/LICENSE
'''

__window__.Close()
import _winreg as wr
k = wr.OpenKey(wr.HKEY_CURRENT_USER,r'Software\Bluebeam Software\Brewery\V45\Printer Driver',0,wr.KEY_WRITE)
wr.SetValueEx(k,r'PromptForFileName',0,wr.REG_SZ,'1')
#wr.QueryValueEx(k,r'PromptForFileName')
wr.FlushKey(k)
k.Close()
print('Done...Bluebeam Ask for Filename Dialog Enabled...')