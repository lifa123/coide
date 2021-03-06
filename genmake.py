#!/usr/bin/env python
import os
import re
from properties import Properties
from system import listAllPackages
import utils
import templates
from threading import Thread
from globals import is_src_ext, src_exts


root=os.path.abspath('.')

genThread=None
genThreadDoneFlag=False

def waitForThread():
    global genThread
    global genThreadDoneFlag
    if genThread:
        genThread.join()
        genThread=None
        genThreadDoneFlag=True

def genThreadDone():
    global genThreadDoneFlag
    if genThread:
        if genThread.isAlive():
            return False
        else:
            genThreadDoneFlag=True
    res=genThreadDoneFlag
    genThreadDoneFlag=False
    return res
    
def mkProps(props, dir):
    path=os.path.join(dir,'mk.cfg')
    if os.path.exists(path):
        p=Properties(path)
        for name in p.keys():
            value=p.get(name)
            if value.startswith('\\'):
                value=props.get(name)+' '+value[1:]
            props.assign(name,value)
    return props

packages=listAllPackages()

class C:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    
def prt(c,s):
    print c + s + C.ENDC

def green(s):
    prt(C.GREEN,s)
    
def red(s):
    prt(C.RED,s)
    
def blue(s):
    prt(C.BLUE,s)
    
    
def isSourceDir(dir,files):
    if dir.count('/')==0:
        return False
    for f in files:
        if is_src_ext(f):
            return True
    return False
    
def filterSources(files):
    alt=[]
    for f in files:
        if is_src_ext(f):
            alt.append(f)
    return alt
    
def arreplace(a,fr,to):
    res=[]
    for s in a:
        res.append(s.replace(fr,to))
    return res

def verifyDir(dir):
    '''
    Check if a directory exists, and if not, create it
    '''
    if not os.path.exists(dir):
        os.makedirs(dir)
        
def isSourceFile(f):
    '''
    Check if a file is a C++ source file
    '''
    return is_src_ext(f)

def findMain(dir):
    '''
    Search the directory for a source file that
    has the `main` function
    '''
    pat=re.compile('^(int|void)( )+main( )*\(')
    files=os.listdir(dir)
    for f in files:
        if isSourceFile(f):
            path=os.path.join(dir,f)
            lines=open(path,"r").readlines()
            for line in lines:
                if re.search(pat,line.strip()):
                    return True
    return False

flagsPat=re.compile('\((.+)\)')
def extractFlags(s):
    m=re.search(flagsPat,s)
    if m:
        g=m.groups()
        return g[0]
    return ""
    
stdIncludes=[]

def fillStdIncludes():
    (out,err)=utils.call('.','/usr/bin/env','g++','-E','-x','c++','-','-v')
    found=False
    for line in err.split('\n'):
        line=line.strip()
        if line == 'End of search list.':
            found=False
        if line == '#include <...> search starts here:':
            found=True
        else:
            if found:
                stdIncludes.append(line)

class Generator:
    def __init__(self,root):
        if len(stdIncludes)==0:
            fillStdIncludes()
        self.root=root
        self.globalInc=os.path.join(root,'include')
        self.srcDir=os.path.join(root,'src')
        self.intrDir=os.path.join(root,'.intr')
        self.outDir=os.path.join(root,'out')
        self.scanWorkspace()
        self.cppcheck=utils.checkFor('cppcheck')
        
    def scanWorkspace(self):
        self.wsLibs={}
        for dir,subdirs,files in os.walk(self.srcDir):
            type=""
            if isSourceDir(dir,files):
                mkPath=os.path.join(dir,'mk.cfg')
                if os.path.exists(mkPath):
                    props=Properties(mkPath)
                    if props.has("TYPE"):
                        type=props.get("TYPE")
                if type=="":
                    if findMain(dir):
                        type="APP"
                    else:
                        type="LIB"
                if type=="LIB":
                    dirname=(dir.split('/'))[-1]
                    self.wsLibs[dirname]=os.path.relpath(dir,self.srcDir)
                    
    def findAllSubdirs(self,files):
        res=[]
        for f in files:
            d=os.path.dirname(f)
            if not d in res:
                res.append(d)
        return res
        
    def addSettings(self,flags,props,cfg,prefix):
        from build_settings_cfg import tabs
        parenPat=re.compile('.+\((.+)\)')
        for t in tabs:
            desc=tabs.get(t)
            for d in desc:
                name=d[0]
                if name.startswith(prefix) or name.startswith('BUILD_'):
                    value=props.get(name)
                    if d[2]=='CB':
                        if value=='True':
                            flags=flags+' '+d[4]
                    else:
                        if value and not value=='Default':
                            m=re.match(parenPat,value)
                            if m:
                                g=m.groups()
                                value=g[0]
                            else:
                                value=value.replace('\\n',' ')
                            flags=flags+' '+value
        return flags
        
    def addCompileSettings(self,cflags,props,cfg):
        return self.addSettings(cflags,props,cfg,'COMPILE_')

    def addLinkSettings(self,lflags,props,cfg):
        return self.addSettings(lflags,props,cfg,'LINK_')

    def generateConfig(self,dir,files,cfg,o,props):
        '''
        Generate rules for a configuration (Debug/Release)
        '''
        name=os.path.basename(dir)
        absdir=os.path.abspath(dir)
        pb=Properties(os.path.join(dir,"mk.cfg"))
        type=pb.get("TYPE")
        if len(type)==0: 
            if findMain(absdir):
                type="APP"
            else:
                type="LIB"
        o.write('TYPE={}\n'.format(type))
        libs=re.split(',| ',pb.get("LINK_LIBS"))
        libs=filter(bool,libs)  # remove empty strings
        if len(type)==0:
            return False
        srcs=filterSources(files)
        subdirs=self.findAllSubdirs(srcs)
        intr=os.path.join(dir.replace(self.srcDir,self.intrDir),cfg)
        verifyDir(intr)
        for sd in subdirs:
            verifyDir(os.path.join(intr,sd))
        outdir=os.path.join(dir.replace(self.srcDir,self.outDir),cfg)
        verifyDir(outdir)
        #reloutdir=os.path.relpath(outdir,dir)
        reloutdir=outdir
        #globalInclude=os.path.relpath(self.globalInc,dir)
        cfgInclude=''
        
        #o = open(output,'w')
        mkProps=Properties()
        o.write('CPP_{}=g++\n'.format(cfg))
        mkProps.assign('CPP_{}'.format(cfg),'g++')
        o.write('INC_{}=-I{} {}\n'.format(cfg,self.globalInc,cfgInclude))
        mkProps.assign('INC_{}'.format(cfg),'-I{} {}'.format(self.globalInc,cfgInclude))

        cflags='-c $(OPT_{}) $(INC_{}) '.format(cfg,cfg)
        cflags=self.addCompileSettings(cflags,props,cfg)
        
        lflags='$(OPT_{}) $(OBJS_{}) '.format(cfg,cfg)
        lflags=self.addLinkSettings(lflags,props,cfg)
        libdeps={}
        for stage in ['local','package']:
            for lib in libs:
                if lib in packages:
                    if stage=='package':
                        cflags=cflags+' `pkg-config --cflags {}` '.format(lib)
                        lflags=lflags+' `pkg-config --libs {}` '.format(lib)
                else:
                    if lib in self.wsLibs:
                        if stage=='local':
                            rel=self.wsLibs.get(lib)
                            libdir=os.path.join(self.root,'out',rel,cfg)
                            libDir=os.path.join(self.root,'src',rel)
                            libProps=Properties(os.path.join(libDir,"mk.cfg"))
                            wPrefix=''
                            wSuffix=''
                            if libProps.get('BUILD_WHOLE_ARCHIVE','False')=='True':
                                wPrefix=' -Wl,--whole-archive'
                                wSuffix='-Wl,--no-whole-archive '
                            lflags=lflags+'{} -L{} -l{} {}'.format(wPrefix,libdir,lib,wSuffix)
                            libdeps[lib]=libDir
                    else:
                        if stage=='package':
                            lflags=lflags+' -l{} '.format(lib)
        o.write('CFLAGS_{}={}\n'.format(cfg,cflags))
        o.write('LFLAGS_{}={}\n'.format(cfg,lflags))
        objs=srcs
        for e in src_exts:
            objs = arreplace(objs,e,'.o')
        for i in xrange(0,len(objs)):
            objs[i]=os.path.join(intr,objs[i])
            
        o.write("OBJS_{}=".format(cfg))
        for obj in objs:
            o.write("\\\n"+obj)
        o.write("\n\n")
        
        liblist=[]

        for lib in libdeps:
            libname="{}_{}".format(lib,cfg)
            liblist.append(libname)
            libpath=libdeps.get(lib)
            o.write("{}:\n".format(libname))
            o.write("\t@make --no-print-directory -C {} {}\n\n".format(libpath,cfg))
            o.write("clean_{}:\n".format(libname))
            o.write("\t@make --no-print-directory -C {} clean_{}\n\n".format(libpath,cfg))
        
        cleanlibs=''
        if type=='LIB':
            outfile='{}/lib{}.a'.format(reloutdir,name)
            o.write('{}: $(OBJS_{})\n'.format(outfile,cfg))
            o.write('\tar cr {} $(OBJS_{})\n\n'.format(outfile,cfg))
        else:
            outfile="{}/{}".format(reloutdir,name)
            o.write('OUTPUT_PATH_{}={}\n\n'.format(cfg,outfile))
            if len(liblist)>0:
                cleanlibs='clean_'+' clean_'.join(liblist)
            liblist=' '.join(liblist)
            o.write('{}: $(OBJS_{}) {}\n'.format(outfile,cfg,liblist))
            o.write('\t$(CPP_{}) -o {} $(LFLAGS_{})\n\n'.format(cfg,outfile,cfg))
            
        o.write('clean_{}: {}\n\t@rm -f $(OBJS_{}) {}\n\n'.format(cfg,cleanlibs,cfg,outfile))        
        o.write('{}: {}\n\n'.format(cfg,outfile))
            
        for i in xrange(0,len(objs)):
            src=os.path.join(absdir,srcs[i])
            depcmd='g++ {} -MM {}'.format(cflags,src)
            depcmd=templates.generateMkCommand(depcmd,mkProps)
            (out,err)=utils.shellcall(dir,depcmd)
            p=out.find(':')
            hdeps=':\n'
            if p>0:
                hdeps=out[p:].replace('\\\n','')
            o.write('{}{}'.format(objs[i],hdeps))
            if self.cppcheck:
                o.write('\tcppcheck {}/{}\n'.format(absdir,srcs[i]))
            o.write('\t$(CPP_{}) $(CFLAGS_{}) -o {} {}/{}\n\n'.format(cfg,cfg,objs[i],absdir,srcs[i]))
            
        return True
        
    def assignDefaults(self,props):
        props.assign("COMPILE_CPP_STD","-std=c++11")
        props.assign("COMPILE_CUSTOM","")
        props.assign("OPT_Release","-O2")
            
    def generate(self,dir,files):
        #props=mkProps(Properties(),root)
        for d,subs,subfiles in os.walk(dir):
            if d!=dir:
                for f in subfiles:
                    files.append(os.path.join(os.path.relpath(d,dir),f))
        stack=[]
        curdir=dir
        while True:
            stack.append(curdir)
            if curdir==self.root:
                break
            curdir=os.path.abspath(os.path.join(curdir,'..'))
        props=Properties()
        self.assignDefaults(props)
        while len(stack)>0:
            props=mkProps(props,stack[-1])
            del stack[-1]
        output=os.path.join(dir,"Makefile")
        o=open(output,"w")
        opt=props.get("OPT_Release")
        if len(opt)==0:
            opt="-O2"
        if opt=="Custom":
            opt=""
        o.write('INC_STD=-I{}\n'.format(' -I'.join(stdIncludes)))
        o.write('OPT_Release={} $(USER_OPT)\n'.format(opt))
        o.write('OPT_Debug=-g $(USER_OPT)\n')
        o.write('\ndefault: Release\n\n')
        o.write('\nclean: clean_Release\n\n')
        self.generateConfig(dir,files,"Release",o,props)
        if self.generateConfig(dir,files,"Debug",o,props):
            pass
        o.write('\nclang_complete:\n')
        o.write('\tclang -cc1 -std=c++11 -x c++ $(INC_STD) $(INC_Release) -w -fsyntax-only ')
        o.write('-code-completion-macros -v -code-completion-at -:$(LINE):$(COL) -\n\n')        

        o.close()
        
def generateTreeRun(root):
    g=Generator(root)
    for (dir,subdirs,files) in os.walk(os.path.join(root,"src")):
        if isSourceDir(dir,files):
            g.generate(dir,files)
            subdirs[:]=[]  # do not recurse down project subdirs

def generateTree(root,blocking):
    global genThread
    if genThread:
        waitForThread()
    if blocking:
        generateTreeRun(root)
    else:
        genThread=Thread(target=generateTreeRun,args=(root,))
        genThread.start()
            
def generateDirectory(root,dir):
    if genThread:
        waitForThread()
    g=Generator(root)
    files=os.listdir(dir)
    if isSourceDir(dir,files):
        g.generate(dir,files)

def unit_test():
    generateTree("src")

if __name__=="__main__":
    unit_test()
    
