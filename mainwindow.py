from PyQt4 import QtCore
from PyQt4 import QtGui

import os
import re
import stat

import qutepart
from workspace import WorkSpace
import output
from consts import FileRole
from gdbwrapper import GDBWrapper
from watchestree import WatchesTree
from breakpoints import BreakpointsDB, BreakpointDialog
from properties import Properties
from functools import partial
from globals import is_src_ext
import utils
import genmake
import uis
import plugins
import dwarf

class MainWindow(QtGui.QMainWindow):
    """ Main IDE Window

    Contains the main code view, along with docking panes for: source files,    
    watches, call stack, and output
    
    """
    LIBRARY_SCAN = "Scanning Libraries"
    
    def __init__(self,rootDir,parent=None):
        """ Initialize.  rootDir indicates where data files are located """
        super(MainWindow,self).__init__(parent)

        s=QtCore.QSettings()
        self.recent_ws=[d for d in s.value('recent_ws','').toString().split(':') if d]

        self.symbolScan=s.value('symbol_scan',True).toBool()
        self.setMinimumSize(QtCore.QSize(1024,768))

        self.currentLine=0
        self.currentFile=''
        self.rootDir=rootDir
        utils.setIconsDir(os.path.join(rootDir,"icons"))
        self.debugger=None
        self.breakpoints=BreakpointsDB()
        self.findDetails=None
        self.scm_mods=[]
        
        self.setWindowIcon(utils.loadIcon('coide'))
        self.setWindowTitle("Coide")

        self.generateQueue=set()        
        self.editors={}
        self.file_times={}
        self.central=QtGui.QTabWidget()
        self.setCentralWidget(self.central)
        self.central.setTabsClosable(True)
        self.central.tabCloseRequested.connect(self.closeTab)
        self.central.currentChanged.connect(self.tabChanged)
        self.tabOrder=[]
        
        self.plugins=plugins.PluginsManager()

        self.setupMenu()
        self.setupContextMenuItems()
        self.setupToolbar(rootDir)
        self.showWorkspacePane()
        self.showOutputPane()
        self.showWatchesPane()
        self.showLocalsPane()
        self.showCallStackPane()
        self.buildProcess=None        
        self.timerCall=None
        

        self.config=s.value("config").toString()
        if self.config=='':
            self.config="Debug"
        self.configCombo.setCurrentIndex(0 if self.config=='Debug' else 1)
        self.workspaceTree.setConfig(self.config)
        
        self.setAllFonts()
        self.loadWindowSettings()
        
        # Debugger timer that is supposed to periodically check 
        # if the program has stopped at a breakpoint
        self.timer=QtCore.QTimer(self)
        self.timer.timeout.connect(self.update)
        self.runningWidget=None
        
        self.asyncPollTimer=QtCore.QTimer(self)
        self.asyncPollTimer.timeout.connect(self.pollAsync)
        
        self.generateTimer=QtCore.QTimer()
        self.generateTimer.timeout.connect(self.timer1000)
        self.generateTimer.start(1000)
        
        self.lowFreqTimer=QtCore.QTimer()
        self.lowFreqTimer.timeout.connect(self.timer5000)
        self.lowFreqTimer.start(5000)
        
        #self.showStatus("Generating All Makefiles")
        #self.timerCall=self.generateAllInThread
        self.timerCall=None
        
        self.paneWatches.hide()
        self.paneLocals.hide()
        self.paneStack.hide()
        
        #self.sc=QtGui.QShortcut("Ctrl+F8",self)
        #self.sc.activated.connect(self.prtsc)
        
    def closeEvent(self, event):
        """ Called before the application window closes

        Informs sub-windows to prepare and saves window settings
        to allow future sessions to look the same
        
        """
        self.workspaceTree.onClose()
        self.workspaceTree.saveTabs(self.central)
        while self.central.count()>0:
            if not self.closeFile():
                event.ignore()
                return

        self.timer.stop()
        self.generateTimer.stop()
        if self.debugger:
            self.debugger.closingApp()
            
        settings = QtCore.QSettings()
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        settings.sync()
        self.removeTempScripts()
        super(MainWindow,self).closeEvent(event)
        
    def saveDebugWindowState(self):
        """
        Save the state of the tool docks, like watches
        and call stack
        """
        settings = QtCore.QSettings()
        settings.setValue("debugWindowState", self.saveState())
        settings.sync()
        
    def loadDebugWindowState(self):
        """
        Restore previous debug windows layout
        """
        settings = QtCore.QSettings()
        self.restoreState(settings.value("debugWindowState").toByteArray())
        
    def loadWindowSettings(self):
        """
        Restore the window size settings from the previous session
        """
        settings = QtCore.QSettings()
        self.restoreGeometry(settings.value("geometry").toByteArray())
        self.restoreState(settings.value("windowState").toByteArray())
        self.loadTabs()
        
    def loadTabs(self):
        self.closeAllTabs()
        ws=self.workspaceTree.settings()
        opentabs=ws.value('opentabs','').toString()
        opentabs=opentabs.split(',')
        for path in opentabs:
            self.openSourceFile(path)
        curtab=ws.value('curtab','').toString()
        if curtab:
            self.setActiveSourceFile(curtab)

    def setupMenu(self):
        """ Creates the application main menu 
        
        The action handlers are also mapped from the toolbar icons
        
        """
        bar=self.menuBar()
        m=bar.addMenu('&File')
        m.addAction(QtGui.QAction('&Initialize Workspace',self,triggered=self.initWorkspace))
        m.addAction(QtGui.QAction('Open &Workspace',self,triggered=self.openWorkspace))
        self.recents_menu=m.addMenu('&Recent Workspaces')
        m.addAction(QtGui.QAction('&Save',self,shortcut='Ctrl+S',triggered=self.saveFile))
        m.addAction(QtGui.QAction('Save &As',self,triggered=self.saveAsFile))
        m.addAction(QtGui.QAction('&Close File',self,shortcut='Ctrl+F4',triggered=self.closeFile))
        m.addAction(QtGui.QAction('E&xit',self,shortcut='Ctrl+Q',triggered=self.exitApp))

        m=bar.addMenu('&Edit')
        m.addAction(QtGui.QAction('&Copy',self,shortcut='Ctrl+C',triggered=self.onCopy))
        m.addAction(QtGui.QAction('C&ut',self,shortcut='Ctrl+X',triggered=self.onCut))
        m.addAction(QtGui.QAction('&Paste',self,shortcut='Ctrl+V',triggered=self.onPaste))
        m.addSeparator()
        m.addAction(QtGui.QAction('&Find/Replace',self,shortcut='Ctrl+F',triggered=self.onFindReplace))
        m.addAction(QtGui.QAction('Find/Replace &Next',self,shortcut='F3',triggered=self.onFindNext))
        
        m=bar.addMenu('&View')
        panes=m.addMenu('Panes')
        panes.addAction(QtGui.QAction('&Workspace',self,triggered=self.onViewPaneWorkspace))
        panes.addAction(QtGui.QAction('&Output',self,triggered=self.onViewPaneOutput))
        m.addAction(QtGui.QAction('&Next Tab',self,shortcut='Ctrl+F6',triggered=self.onViewNextTab))
        
        m=bar.addMenu('&Build')
        m.addAction(QtGui.QAction('&Build',self,shortcut='F7',triggered=self.build))
        m.addAction(QtGui.QAction('&Clean',self,triggered=self.clean))
        m.addAction(QtGui.QAction('&Rebuild',self,shortcut='Shift+F7',triggered=self.rebuild))
        m.addAction(QtGui.QAction('&Settings',self,shortcut='Ctrl+F7',triggered=self.buildSettings))
        m.addAction(QtGui.QAction('&Next Error',self,shortcut='F4',triggered=self.nextError))
        
        m=bar.addMenu('&Debug')
        m.addAction(QtGui.QAction('&Run',self,shortcut='Ctrl+F5',triggered=self.runProject))
        m.addAction(QtGui.QAction('&Start/Continue Debugger',self,shortcut='F5',triggered=self.startDebug))
        ma=m.addMenu('Actions')
        ma.addAction(QtGui.QAction('&Step',self,shortcut='F11',triggered=self.actStep))
        ma.addAction(QtGui.QAction('&Next',self,shortcut='F10',triggered=self.actNext))
        ma.addAction(QtGui.QAction('Step &Out',self,shortcut='Shift+F11',triggered=self.actOut))
        ma.addAction(QtGui.QAction('&Break',self,shortcut='Ctrl+C',triggered=self.actBreak))
        ma.addAction(QtGui.QAction('Sto&p',self,shortcut='Shift+F5',triggered=self.actStop))
        ma=m.addMenu('&Breakpoints')
        ma.addAction(QtGui.QAction('&Clear',self,triggered=self.clearBreakpoints))
        
        m=bar.addMenu('&Settings')
        m.addAction(QtGui.QAction('&General',self,triggered=self.settingsGeneral))
        m.addAction(QtGui.QAction('&Fonts',self,triggered=self.settingsFonts))
        m.addAction(QtGui.QAction('&Editor',self,triggered=self.settingsEditor))
        m.addAction(QtGui.QAction('&Templates',self,triggered=self.settingsTemplates))
        m.addAction(QtGui.QAction('&Plugins',self,triggered=self.settingsPlugins))
        
        m=bar.addMenu('&Tools')
        pm=m.addMenu('&Plugins')
        self.plugins.addToMenu(pm)

    def onViewPaneWorkspace(self):
        self.paneWorkspace.show()

    def onViewPaneOutput(self):
        self.paneOutput.show()
        
    def onViewNextTab(self):
        count=self.central.count()
        if count>0:
            if len(self.tabOrder)!=count:
                self.tabOrder=range(0,self.central.count())
            if self.central.currentIndex() == self.tabOrder[0]:
               self.tabOrder=self.tabOrder[1:]+self.tabOrder[:1] 
            self.central.setCurrentIndex(self.tabOrder[0])

    def setupContextMenuItems(self):
        self.contextMenuItems={
            'all':[
                QtGui.QAction('Toggle Breakpoint',self,triggered=self.contextToggleBreakpoint)
            ],
            'files':[
                QtGui.QAction('Open Header',self,triggered=self.contextOpenHeader)
            ],
            'breakpoints':[
                QtGui.QAction('Edit Breakpoint',self,triggered=self.contextEditBreakpoint),
                QtGui.QAction('Dis/Enable Breakpoint',self,triggered=self.contextAbleBreakpoint)
            ],
            'symbols':[
                QtGui.QAction('Goto Definition',self,triggered=self.contextGotoDefinition)
            ]
        }
        
    def insertContextMenuItems(self,editor,menu):
        first=None
        acts=menu.actions()
        if len(acts)>0:
            first=acts[0]
        actions=list(self.contextMenuItems.get('all'))
        path=editor.path
        line=editor.contextMenuLine
        word=editor.contextMenuWord
        self.context=(path,line,word)
        if len(word)>0:
            actions.extend(self.contextMenuItems.get('symbols'))
        if self.breakpoints.hasBreakpoint(path,line):
            actions.extend(self.contextMenuItems.get('breakpoints'))
        if self.workspaceTree.exists(editor.contextFilename):
            actions.extend(self.contextMenuItems.get('files'))
        menu.insertActions(first,actions)
        menu.insertSeparator(first)
        
    def contextGotoDefinition(self):
        src=os.path.join(self.workspaceTree.root,'src')
        intr=os.path.join(self.workspaceTree.root,'.intr')
        srcpath=self.context[0]
        objpath=''
        if srcpath.startswith(src) and is_src_ext(srcpath):
            rel=srcpath[len(src):]
            rel=rel[1:-4]+'.o'
            objpath=os.path.join(intr,rel)
            (dir,name)=os.path.split(objpath)
            objpath=os.path.join(dir,'Debug',name)
        if srcpath.startswith(self.workspaceTree.root) and srcpath.endswith('.h'):
            dir=self.workspaceTree.mainPath()
            mkPath=os.path.join(dir,'Makefile')
            objpath=utils.objForHeader(mkPath,srcpath)
        if len(objpath)>0:
            try:
                s=dwarf.DwarfSymbols(objpath)
                (path,line)=s.find(self.context[2])
                if len(path)>0:
                    self.goToSource(path,line,1)
            except IOError:
                utils.message('Project must first be compiled in Debug')
                
        
    def contextToggleBreakpoint(self):
        e=self.central.currentWidget()
        self.breakpoints.toggleBreakpoint(e)
        e.update()
        
    def contextEditBreakpoint(self):
        e=self.central.currentWidget()
        path=e.path
        line=e.contextMenuLine
        bp=self.breakpoints.getBreakpoint(path,line)
        if bp:
            d=BreakpointDialog()
            d.condition.setText(bp.condition())
            utils.setCheckbox(d.enabled,bp.isEnabled())
            if d.exec_():
                bp.setCondition(d.condition.text())
                bp.able(utils.getCheckbox(d.enabled))
                self.breakpoints.update()
                e.update()
                
    def contextAbleBreakpoint(self):
        e=self.central.currentWidget()
        path=e.path
        line=e.contextMenuLine
        bp=self.breakpoints.getBreakpoint(path,line)
        if bp:
            if bp.isEnabled():
                bp.disable()
            else:
                bp.enable()
            self.breakpoints.update()
            e.update()
        
    def contextOpenHeader(self):
        e=self.central.currentWidget()
        filename=self.workspaceTree.exists(e.contextFilename)
        if filename:
            self.workspaceTree.openFile(filename)

    def markToggleBreakpoint(self,line):
        e=self.central.currentWidget()
        #path=e.path
        self.breakpoints.toggleBreakpoint(e)
        e.update()

    def createPluginCuror(self):
        from pcursor import PluginCursor
        e=self.central.currentWidget()
        if e:
            return PluginCursor(e.textCursor())
        return None

    def setupToolbar(self,rootDir):
        """ Creates the application main toolbar """
        tb=self.addToolBar('Actions')
        tb.setObjectName("Toolbar")
        tb.addAction(utils.loadIcon('gear'),'Generate Makefiles').triggered.connect(self.generate)
        self.configCombo=self.createConfigCombo(tb)
        tb.addWidget(self.configCombo)
        tb.addAction(utils.loadIcon('step.png'),'Step').triggered.connect(self.actStep)
        tb.addAction(utils.loadIcon('next.png'),'Next').triggered.connect(self.actNext)
        tb.addAction(utils.loadIcon('out.png'),'Out').triggered.connect(self.actOut)
        tb.addAction(utils.loadIcon('cont.png'),'Continue').triggered.connect(self.actCont)
        tb.addAction(utils.loadIcon('break.png'),'Break').triggered.connect(self.actBreak)
        tb.addAction(utils.loadIcon('stop.png'),'Stop').triggered.connect(self.actStop)
        self.createTemplatesCombo(tb)
        tb.addWidget(self.tmplCombo)

    def exitApp(self):
        self.close()
        
    def nextError(self):
        e=self.outputEdit.getNextError()
        if e:
            self.showStatus(e[3])
            self.goToSource(e[0],e[1],e[2],'#ff8080')
            self.outputEdit.highlightLine(e[4])

    def onCopy(self):
        (e,p)=self.currentEditor()        
        if e:
            e.copy()
        
    def onCut(self):
        (e,p)=self.currentEditor()        
        if e:
            e.cut()
        
    def onPaste(self):
        (e,p)=self.currentEditor()        
        if e:
            e.paste()
        
    def onFindReplace(self):
        (e,p)=self.currentEditor()        
        if e:
            from finddlg import FindDialog
            d=FindDialog(self)
            c=e.textCursor()
            if c.hasSelection:
                d.setFindText(c.selectedText())
            if d.exec_():
                self.findDetails=d.details
                self.onFindNext()
        
    def onFindNext(self):
        (e,p)=self.currentEditor()
        if e and self.findDetails:
            flags=QtGui.QTextDocument.FindFlags()
            if not self.findDetails.get('find_case'):
                flags = flags | QtGui.QTextDocument.FindCaseSensitively
            if self.findDetails.get('find_words'):
                flags = flags | QtGui.QTextDocument.FindWholeWords
            if self.findDetails.get('find_back'):
                flags = flags | QtGui.QTextDocument.FindBackward
            text=self.findDetails.get('find_text')
            replaceText=self.findDetails.get('find_replace_text')
            replace=self.findDetails.get('find_replace')
            all=self.findDetails.get('find_all')
            if all and replace:
                while e.find(text,flags):
                    e.textCursor().insertText(replaceText)
            elif e.find(text,flags):
                if replace:
                    e.textCursor().insertText(replaceText)
        
    def settingsTemplates(self):
        """ Show the code templates editing dialog """
        from settings import TemplatesDialog
        d=TemplatesDialog()
        if d.exec_():
            d.save()
            self.updateTemplates()
            
    def settingsPlugins(self):
        """ Show the python plugins settings dialog """
        from plugins import PluginsDialog
        d=PluginsDialog()
        if d.exec_():
            d.save()

    def settingsGeneral(self):
        """ Show the general settings """
        from settings import GeneralSettingsDialog
        d=GeneralSettingsDialog()
        if d.exec_():
            d.save()
            self.updateGeneralSettings()

    def settingsEditor(self):
        """ Show the editor settings """
        from settings import EditorSettingsDialog
        d=EditorSettingsDialog()
        if d.exec_():
            d.save()
            self.updateEditorsSettings()

    def settingsFonts(self):
        """ Edit the font settings for the code window and various panes """
        from settings import FontSettingsDialog
        d=FontSettingsDialog()
        if d.exec_():
            self.setAllFonts()
            
    def loadFont(self,name,target):
        """ Load previously saved font settings """
        settings=QtCore.QSettings()
        if settings.contains(name):
            fb=settings.value(name).toByteArray()
            buf=QtCore.QBuffer(fb)
            buf.open(QtCore.QIODevice.ReadOnly)
            font=QtGui.QFont()
            QtCore.QDataStream(fb) >> font
            target.setFont(font)
        else:
            target.setFont(QtGui.QFont('Monospace',14))
        
    def setAllFonts(self):
        """ Apply fonts to the various sub-windows """
        for e in self.editors:
            self.loadFont('codefont',self.editors.get(e))
        #self.loadFont('watchesfont',self.watchesTree)
        #self.loadFont('watchesfont',self.stackList)
        self.loadFont('watchesfont',self.outputEdit)
        self.loadFont('sourcesfont',self.workspaceTree)
        
    def updateGeneralSettings(self):
        """ Apply general settings """
        s=QtCore.QSettings()
        sortFiles=s.value('sortFiles',True).toBool()
        self.workspaceTree.setSorting(sortFiles)
        
    def updateEditorsSettings(self):
        """ Apply editor settings to all open tabs """
        s=QtCore.QSettings()
        indent=(s.value('indent',2).toInt())[0]
        clang=s.value('clangCompletion',True).toBool()
        for e in self.editors:
            self.editors.get(e).indentWidth=indent
            self.editors.get(e).clangCompletion=clang
            
    def updateTemplates(self):
        self.tmplCombo.clear()
        self.tmplCombo.addItem("= Templates =")
        d=QtCore.QSettings().value('tmplDir','').toString()
        if d:
            templates=os.listdir(d)
            templates=[os.path.splitext(t)[0] for t in templates if t.endswith('.template')]
            for t in templates:
                self.tmplCombo.addItem(t)
        
    def showStatus(self,status):
        self.statusBar().showMessage(status)
        
    def findUndefinedReferences(self,output):
        """
        Search the linker output to find undefined reference
        errors, and collect the missing symbol names
        """
        undefined=set()
        base='undefined reference to '
        if output:
            for line in output:
                p=line.find(base)
                if p>0:
                    name=line[(p+len(base)):]
                    if name.startswith('symbol '):
                        name=name[8:]
                    else:
                        name=name[1:]
                    p=name.find('(')
                    if p>0:
                        name=name[0:p]
                    else:
                        name=name[0:len(name)-1]
                    p=name.find('@')
                    if p>0:
                        name=name[0:p]
                    undefined.add(name)
        return undefined

    def toggleAdded(self,item):
        if item.checkState():
            self.added.add(item.text())
        else:
            self.added.remove(item.text())
        
    def attemptUndefResolution(self,undefs):
        if not self.symbolScan:
            return
        from system import getLibrarySymbols, getWorkspaceSymbols
        suggested={}
        syms=getLibrarySymbols()
        wsSyms=getWorkspaceSymbols()
        for sym in undefs:
            words=sym.split(':')
            words=[w for w in words if w]
            words.append(sym)
            for word in words:
                if word in syms:
                    s=syms.get(word)
                    for l in s:
                        if not l in suggested:
                            suggested[l]=1
                        else:
                            n=suggested.get(l)+1
                            suggested[l]=n
                if word in wsSyms:
                    s=wsSyms.get(word)
                    for l in s:
                        if not l in suggested:
                            suggested[l]=1
                        else:
                            n=suggested.get(l)+1
                            suggested[l]=n
        self.added=set()
        if len(suggested)>0:
            d=uis.loadDialog('libsuggest')
            model = QtGui.QStandardItemModel(d.libsList)
            for s in suggested:
                item=QtGui.QStandardItem(s)
                item.setCheckable(True)
                model.appendRow(item)
            d.libsList.setModel(model)
            model.itemChanged.connect(lambda item : self.toggleAdded(item))
            if d.exec_():
                self.workspaceTree.addLibrariesToProject(self.added)
        
        
    def buildSettings(self,path=''):
        from buildsettings import BuildSettingsDialog
        if not path:
            path=self.workspaceTree.mainPath()
            if not path:
                path=self.workspaceTree.root
        d=BuildSettingsDialog(self,path)
        d.exec_()
        self.generateQueue.add(path)
        
    def checkBuildOutput(self):
        if self.buildProcess:
            self.processBuildOutput(self.buildProcess.text)
            self.buildProcess=None

    def pollAsync(self):
        rcs=utils.pollAsync()
        if len(rcs)>0:
            if rcs[0]==0:
                utils.appendColorLine(self.outputEdit,"Success...",'#008020')
            else:
                utils.appendColorLine(self.outputEdit,"= Failed ({}) =".format(rcs[0]),'#ff0000')
            self.checkBuildOutput()
            self.asyncPollTimer.stop()
            self.showStatus("Done")
            
    def execute(self,path,cmd,*args):
        if utils.pendingAsync():
            self.showStatus('Busy')
            return None
        self.outputEdit.clearAll()
        p=utils.execute(self.outputEdit,path,cmd,*args)
        if not self.asyncPollTimer.isActive():
            self.asyncPollTimer.start(10)
        return p
        
    def buildSpecific(self,path):
        self.saveAll()
        self.autoGenerate()
        if len(path)>0:
            self.showStatus("Building "+os.path.basename(path))
            s=QtCore.QSettings()
            if s.value('parallel_make',False).toBool():
                self.buildProcess=self.execute(path,'/usr/bin/make','-j',self.config)
            else:
                self.buildProcess=self.execute(path,'/usr/bin/make',self.config)
                
    def processBuildOutput(self,output):
        undefs=self.findUndefinedReferences(output)
        if len(undefs)>0:
            self.attemptUndefResolution(undefs)
        
    def build(self):
        self.buildSpecific(self.workspaceTree.mainPath())
            
    def cleanSpecific(self,path):
        if len(path)>0:
            self.execute(path,'/usr/bin/make','clean_{}'.format(self.config))
        
    def clean(self):
        self.cleanSpecific(self.workspaceTree.mainPath())

    def rebuildSpecific(self,path):
        if len(path)>0:
            cfg=self.config
            self.showStatus("Rebuilding "+os.path.basename(path))
            self.buildProcess=self.execute(path,'/usr/bin/make','clean_'+cfg,cfg)
    
    def rebuild(self):
        self.rebuildSpecific(self.workspaceTree.mainPath())
        
    def autoGenerateRun(self):
        for path in self.generateQueue:
            genmake.generateDirectory(self.workspaceTree.root,path)
        self.generateQueue.clear()
        self.showStatus('Ready')
        
    def autoGenerate(self):
        if len(self.generateQueue)>0:
            self.showStatus('Generating Makefiles')
            self.timerCall=self.autoGenerateRun
        else:
            if genmake.genThreadDone():
                self.showStatus("Makefile Generate Done")
        
    def waitForScanner(self):
        if self.symbolScan:
            import system
            import time
            while not system.isScannerDone():
                time.sleep(1)
        
    def timer1000(self):
        e=self.central.currentWidget()
        if e:
            updates=self.breakpoints.updateLineNumbers(e.path)
            for path in updates:
                e=self.editors.get(path)
                if e:
                    e.update()
        if self.timerCall:
            f=self.timerCall
            self.timerCall=None
            f()
        self.autoGenerate()
        #if self.statusBar().currentMessage() == MainWindow.LIBRARY_SCAN:
        if self.symbolScan:
            import system
            if system.isScannerDone():
                #if system.scanq and not system.scanq.empty():
                if self.statusBar().currentMessage() == MainWindow.LIBRARY_SCAN:
                    self.showStatus('Ready')
                system.getLibrarySymbols()
                
    def timer5000(self):
        import scm
        res=scm.scan(self.workspaceTree.root)
        if res:
            new_scm_mods=[]
            for (name,status) in res:
                path=os.path.join(self.workspaceTree.root,name)
                if path in self.workspaceTree.fileItems:
                    item=self.workspaceTree.fileItems.get(path)
                    if status=='Modified':
                        item.setForeground(0,QtGui.QBrush(QtGui.QColor(255,0,0)))
                    elif status=='Staged':
                        item.setForeground(0,QtGui.QBrush(QtGui.QColor(0,255,0)))
                    new_scm_mods.append(item)
            for item in self.scm_mods:
                if not item in new_scm_mods:
                    item.setForeground(0,QtGui.QBrush(QtGui.QColor(0,0,0)))
            self.scm_mods=new_scm_mods
        for path in self.editors:
            last=self.file_times.get(path)
            cur=os.path.getmtime(path)
            if cur!=last:
                self.file_times[path]=cur
                res=QtGui.QMessageBox.question(self,'File changed','Reload {}'.format(path),QtGui.QMessageBox.Yes,QtGui.QMessageBox.No)
                if res==QtGui.QMessageBox.Yes:
                    text=''.join(open(path,'r').readlines())
                    self.editors.get(path).text=text
                
            
    def generateAllInThread(self):
        genmake.generateTree(self.workspaceTree.root,False)
        
    def generateAll(self):
        genmake.generateTree(self.workspaceTree.root,True)
        
    def generate(self):
        mb=QtGui.QMessageBox()
        mb.setText("Generate make files")
        mb.setInformativeText("Overwrite all make files?")
        mb.setStandardButtons(QtGui.QMessageBox.Yes|QtGui.QMessageBox.No)
        mb.setDefaultButton(QtGui.QMessageBox.Yes)
        rc=mb.exec_()
        if rc==QtGui.QMessageBox.Yes:
            self.generateAll()
            utils.message("Done")
            
    def createHelloWorldProject(self,dir):
        try:
            os.makedirs(dir)
        except OSError:
            pass
        mainpath=os.path.join(dir,'main.cpp')
        f=open(mainpath,"w")
        f.write('#include <iostream>\n\n\nint main(int argc, char* argv[])\n')
        f.write('{\n  std::cout << "Hello World" << std::endl;\n  return 0;\n}\n')
        f.close()
        self.workspaceTree.update()
        genmake.generateDirectory(self.workspaceTree.root,dir)
        self.workspaceTree.setMainPath(dir)

    def initWorkspace(self):
        d=QtGui.QFileDialog()
        d.setFileMode(QtGui.QFileDialog.Directory)
        d.setOption(QtGui.QFileDialog.ShowDirsOnly)
        if d.exec_():
            ws=(d.selectedFiles())[0]
            os.makedirs(os.path.join(ws,'include'))
            dir=os.path.join(ws,'src','hello')
            self.workspaceTree.setWorkspacePath(ws)
            self.createHelloWorldProject(dir)
            self.workspaceTree.saveSettings()
            self.generateAll()
            
    def updateRecents(self):
        ws=self.workspaceTree.root
        if ws in self.recent_ws:
            del self.recent_ws[self.recent_ws.index(ws)]
        self.recent_ws.insert(0,ws)
        while len(self.recent_ws)>4:
            del self.recent_ws[-1]
        s=QtCore.QSettings()
        s.setValue('recent_ws',':'.join(self.recent_ws))
        s.sync()
        self.recents_menu.clear()
        handlers=[partial(self.openRecent,w) for w in self.recent_ws]
        for ws,h in zip(self.recent_ws,handlers):
            self.recents_menu.addAction(QtGui.QAction(ws,self,triggered=h))

    def openRecent(self,ws):
        self.workspaceTree.saveTabs(self.central)
        self.closeAllTabs()
        self.workspaceTree.setWorkspacePath(ws)
        #self.generateAll()
        self.loadTabs()
        self.waitForScanner()
        import symbolscanner
        symbolscanner.setWorkspacePath(ws)
        self.updateRecents()

    def openWorkspace(self):
        d=QtGui.QFileDialog()
        d.setFileMode(QtGui.QFileDialog.Directory)
        d.setOption(QtGui.QFileDialog.ShowDirsOnly)
        if d.exec_():
            ws=(d.selectedFiles())[0]
            self.openRecent(ws)

    def saveTabFile(self,index):
        n=self.central.tabBar().count()
        if index>=0 and index<n:
            path=self.central.tabToolTip(index)
            editor=self.editors.get(path)
            if editor:
                doc=editor.document()
                if doc.isModified():
                    f=open(path,'w')
                    if not f:
                        utils.errorMessage('Cannot write file: {}'.format(path))
                        return
                    f.write(doc.toPlainText())
                    f.close()
                    doc.setModified(False)
                    self.file_times[path]=os.path.getmtime(path)
                    #dir=os.path.dirname(path)
                    #self.generateQueue.add(dir)
                    if self.symbolScan:
                        from system import getLibrarySymbols
                        getLibrarySymbols()
                        from symbolscanner import rescanOnFileSave
                        rescanOnFileSave(path)


    def saveFile(self):
        n=self.central.tabBar().count()
        if n>0:
            self.saveTabFile(self.central.currentIndex())
                    
    def saveAll(self):
        n=self.central.tabBar().count()
        for i in xrange(0,n):
            self.saveTabFile(i)

    def saveAsFile(self):
        pass
    
    def closeAllTabs(self):
        while self.central.count()>0:
            if not self.closeTab(0):
                return False
        return True
    
    def tabChanged(self,index):
        for i in xrange(0,len(self.tabOrder)):
            if self.tabOrder[i]==index:
                self.tabOrder=self.tabOrder[i:]+self.tabOrder[:i]
                break

    def closeTab(self,index):
        path=self.central.tabToolTip(index)
        editor=self.editors.get(path)
        if editor:
            doc=editor.document()
            if doc.isModified():
                mb = QtGui.QMessageBox()
                mb.setText("{} has been modified.".format(os.path.basename(path)))
                mb.setInformativeText("Do you want to save your changes?")
                mb.setStandardButtons(QtGui.QMessageBox.Save | QtGui.QMessageBox.Discard | QtGui.QMessageBox.Cancel)
                mb.setDefaultButton(QtGui.QMessageBox.Save)
                rc = mb.exec_()
                if rc == QtGui.QMessageBox.Save:
                    f=open(path,'w')
                    if not f:
                        utils.errorMessage('Cannot write file: {}'.format(path))
                        return False
                    f.write(doc.toPlainText())
                    f.close()
                elif rc == QtGui.QMessageBox.Cancel:
                    return False
            del self.editors[path]
            del self.file_times[path]
        self.central.removeTab(index)
        return True

    def closeFile(self):
        n=self.central.tabBar().count()
        if n>0:
            index=self.central.currentIndex()
            return self.closeTab(index)
        return False
            
    def currentEditor(self):
        if self.central.count()>0:
            cur=self.central.currentIndex()
            path=self.central.tabToolTip(cur)
            if path in self.editors:
                return (self.editors.get(path),path)
        return (None,None)

    def templateSelected(self,index):
        (editor,path)=self.currentEditor()
        if index>0 and editor:
            template=self.tmplCombo.itemText(index)
            d=QtCore.QSettings().value('tmplDir','').toString()
            if d:
                tpath=os.path.join(d,template+".template")
                try:
                    f=open(tpath,'r')
                    code=f.read()
                    if code:
                        cursor=editor.textCursor()
                        props=Properties()
                        props.assign('PATH',path)
                        base=os.path.basename(path)
                        props.assign('FILENAME',base)
                        p=base.find('.')
                        if (p>0):
                            props.assign('FILEBASE',base[0:p])
                        props.assign('SELECTION',cursor.selectedText())
                        cursor.removeSelectedText()
                        import templates
                        text=templates.generateCode(code,props)
                        cursor.insertText(text)
                except IOError:
                    utils.errorMessage("Cannot read file: {}".format(path))
        self.tmplCombo.setCurrentIndex(0)        
                

    def showWorkspacePane(self):
        """ Creates a docking pane that shows a list of source files """
        self.paneWorkspace=QtGui.QDockWidget("Workspace",self)
        self.paneWorkspace.setObjectName("Workspace")
        self.paneWorkspace.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea|QtCore.Qt.RightDockWidgetArea)
        self.workspaceTree=WorkSpace(self.paneWorkspace,self)
        self.workspaceTree.depsChanged.connect(lambda path: self.generateQueue.add(path))
        self.paneWorkspace.setWidget(self.workspaceTree)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea,self.paneWorkspace)
        self.updateWorkspace()
        self.workspaceTree.doubleClicked.connect(self.docDoubleClicked)
        self.showStatus(MainWindow.LIBRARY_SCAN)
        if self.symbolScan:
            from system import startSymbolScan
            startSymbolScan(self.workspaceTree.root)
        else:
            from system import disableSymbolScan
            disableSymbolScan()
        self.updateRecents()
        
    def updateWorkspace(self):
        self.workspaceTree.update()
        
    def setActiveSourceFile(self,path):
        if path in self.editors:
            editor=self.editors.get(path)
            n=self.central.tabBar().count()
            for i in xrange(0,n):
                if self.central.widget(i) == editor:
                    self.central.tabBar().setCurrentIndex(i)
                    return True
        return False
        
    def fixPath(self,path):
        if path.startswith(self.rootDir):
            path=os.path.relpath(path,self.rootDir)
        return path
        
    '''
    Makes the path given the active source file in the editor.
    If the file is already open, it is made active.
    If not, it is opened and made active.
    Function returns true if the file is found and opened
    '''
    def openSourceFile(self,path):
        path=self.fixPath(path)
        if self.setActiveSourceFile(path):
            return True
        else:
            try:
                f=open(path,"r")
                if not f:
                    return False
                lines=f.readlines()
                if lines:
                    firstLine=lines[0]
                    s=QtCore.QSettings()
    
                    editor=qutepart.Qutepart()
                    editor.setPath(path)
                    editor.detectSyntax(sourceFilePath=path, firstLine=firstLine)
                    editor.lineLengthEdge = 1024
                    editor.drawIncorrectIndentation = True
                    editor.drawAnyWhitespace = False
                    editor.indentUseTabs = False
                    editor.indentWidth = (s.value('indent',2).toInt())[0]
                    editor.text="".join(lines)
                    editor.setLineWrapMode(QtGui.QPlainTextEdit.NoWrap)
                    editor.setWorkspace(self.workspaceTree)
                    editor.setMainWindow(self)
                    index=self.central.addTab(editor,os.path.basename(path))
                    self.central.setTabToolTip(index,path)
                    self.editors[path]=editor
                    self.file_times[path]=os.path.getmtime(path)
                    self.loadFont('codefont',editor)
                    self.central.tabBar().setCurrentIndex(index)
                    bps=self.breakpoints.pathBreakpoints(path)
                    editor.bpMarks=bps
                    editor._markArea.blockDoubleClicked.connect(self.markToggleBreakpoint)
                    return True
            except IOError:
                return False
        return False

    def docDoubleClicked(self,index):
        item=self.workspaceTree.currentItem()
        path=item.data(0,FileRole).toString()
        if len(path)>0:
            self.openSourceFile(path)
            if path in self.editors:
                self.editors.get(path).setFocus(QtCore.Qt.MouseFocusReason)

    def goToSource(self,path,row,col,color=''):
        """
        Given a file path, and a position within, open a tab
        or switch to an already open tab, and scroll to that
        position.  Usually useful to find references or 
        compiler error positions
        """
        path=self.fixPath(path)
        if self.openSourceFile(path):
            editor=self.editors.get(path)
            if editor:
                self.setActiveSourceFile(path)
                c=editor.textCursor()
                c.movePosition(QtGui.QTextCursor.Start)
                c.movePosition(QtGui.QTextCursor.Down,n=row-1)
                c.movePosition(QtGui.QTextCursor.Right,n=col-1)
                editor.setTextCursor(c)
                editor.ensureCursorVisible()
                if len(color)>0:
                    editor.colorLine(row,color)
        
    def showCallStackPane(self):
        self.paneStack=QtGui.QDockWidget("Call Stack",self)
        self.paneStack.setObjectName("CallStack")
        self.paneStack.setAllowedAreas(QtCore.Qt.BottomDockWidgetArea)
        self.stackList=QtGui.QListWidget(self.paneStack)
        self.paneStack.setWidget(self.stackList)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea,self.paneStack)
        self.loadFont('watchesfont',self.stackList)
        self.stackList.itemDoubleClicked.connect(self.stackItemDoubleClicked)
    
    def showLocalsPane(self):
        self.paneLocals=QtGui.QDockWidget("Locals",self)
        self.paneLocals.setObjectName("Locals")
        self.paneLocals.setAllowedAreas(QtCore.Qt.BottomDockWidgetArea)
        self.localsTree=WatchesTree(self.paneLocals)
        self.localsTree.setColumnCount(2)
        self.localsTree.setHeaderLabels(['Name','Value'])
        self.paneLocals.setWidget(self.localsTree)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea,self.paneLocals)
        self.loadFont('watchesfont',self.watchesTree)
    
    def showWatchesPane(self):
        self.paneWatches=QtGui.QDockWidget("Watches",self)
        self.paneWatches.setObjectName("Watches")
        self.paneWatches.setAllowedAreas(QtCore.Qt.BottomDockWidgetArea)
        self.watchesTree=WatchesTree(self.paneWatches)
        self.watchesTree.setColumnCount(2)
        self.watchesTree.setHeaderLabels(['Name','Value'])
        self.paneWatches.setWidget(self.watchesTree)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea,self.paneWatches)
        self.loadFont('watchesfont',self.watchesTree)
        self.watchesTree.addTopLevelItem(QtGui.QTreeWidgetItem(['* Double-Click for new watch']))
        self.watchesTree.resizeColumnToContents(0)
        self.watchesTree.itemDoubleClicked.connect(lambda item,column : self.watchDoubleClicked(item,column))
        
        
    def showOutputPane(self):        
        self.paneOutput=QtGui.QDockWidget("Output",self)
        self.paneOutput.setObjectName("Output")
        self.paneOutput.setAllowedAreas(QtCore.Qt.BottomDockWidgetArea)
        self.outputEdit=output.OutputWidget(self.paneOutput,self)
        self.outputEdit.setReadOnly(True)
        self.paneOutput.setWidget(self.outputEdit)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea,self.paneOutput)

    def stackItemDoubleClicked(self,item):
        pat='at (.+):(\d+)'
        m=re.search(pat,item.text())
        if m:
            g=m.groups()
            path=g[0]
            line=int(g[1])
            self.goToSource(path,line,1)
        else:
            row=self.stackList.row(item)
            if row<(self.stackList.count()-1):
                self.stackItemDoubleClicked(self.stackList.item(row+1))
        

    def watchDoubleClicked(self,item,column):
        """ Edits existing watches, or adds a new watch """
        changed=False
        index=self.watchesTree.indexOfTopLevelItem(item)
        if item.text(column)=='* Double-Click for new watch':
            res=QtGui.QInputDialog.getText(self,'New Watch','Expression')
            expr=res[0]
            if len(expr)>0 and res[1]:
                self.watchesTree.insertTopLevelItem(index,QtGui.QTreeWidgetItem([expr]))
                changed=True
                self.updateWatches()
        else:
            watch=item.text(0)
            res=QtGui.QInputDialog.getText(self,"Edit Watch",'Expression',text=watch)
            watch=res[0]
            if res[1]:
                changed=True
                if len(watch)>0:
                    item.setText(0,watch)
                    self.updateWatches()
                else:
                    self.watchesTree.takeTopLevelItem(index)
        if changed:
            self.saveWatches()


    def createConfigCombo(self,parent):
        configCombo=QtGui.QComboBox(parent)
        configCombo.addItem("Debug")
        configCombo.addItem("Release")
        configCombo.currentIndexChanged.connect(self.configChanged)
        return configCombo
        
    def createTemplatesCombo(self,parent):
        self.tmplCombo=QtGui.QComboBox(parent)
        self.tmplCombo.currentIndexChanged.connect(self.templateSelected)
        self.updateTemplates()
        
    def configChanged(self,index):
        configs=['Debug','Release']
        self.config=configs[index]
        s=QtCore.QSettings()
        s.setValue("config",self.config)
        s.sync()
        self.workspaceTree.setConfig(self.config)
        
    def addOutputText(self,added):
        """ Append the new text captured
        
        Text is appended to the end of existing text and the widget
        is scrolled to show the end 
        
        """
        text=self.outputEdit.toPlainText()
        self.outputEdit.setPlainText(text+added)
        c=self.outputEdit.textCursor()
        c.movePosition(QtGui.QTextCursor.End)
        self.outputEdit.setTextCursor(c)
        self.outputEdit.ensureCursorVisible()
        
    def tempScriptPath(self):
        """
        Generate a temporary script name.  Used for running programs
        with an additional wait for key at the end.
        """
        from time import time
        t=int(time()*10)
        return '/tmp/coide_{}.sh'.format(t)
        
    def removeTempScripts(self):
        """
        Remove all temporary script files.  Called before program
        exit
        """
        files=os.listdir('/tmp')
        files=[f for f in files if f.startswith('coide_')]
        for f in files:
            os.remove('/tmp/{}'.format(f))
        
    def runProject(self):
        if not utils.checkFor('xterm'):
            utils.message("xterm not installed")
            return
        path=self.tempScriptPath()
        f=open(path,'w')
        dir=self.workspaceTree.getDebugDirectory()
        cmd=self.workspaceTree.getExecutablePath()
        params=self.workspaceTree.getDebugParams()
        if len(params)>0:
            cmd=cmd+" "+params
        f.write('#!/bin/sh\ncd {}\n{}\nread -r -p "Press any key..." key\n'.format(dir,cmd))
        f.close()
        os.chmod(path,stat.S_IRUSR|stat.S_IWUSR|stat.S_IXUSR)
        utils.run('/tmp','xterm','-fn','10x20','-e',path)
        
    def getCurrentFile(self):
        if self.central.count()==0:
            return ''
        return self.central.tabToolTip(self.central.currentIndex())
        
    def getCurrentEditor(self):
        path=self.getCurrentFile()
        if len(path)>0:
            return self.editors.get(path)
        
    def updatePosition(self):
        """ Query current position and update the code view """
        changed=False
        poslist=self.debugger.getCurrentPos()
        if poslist and len(poslist)>0:
            for (path,line) in poslist:
                if self.getCurrentFile()==path:
                    if self.currentLine!=line:
                        changed=True
                    break
                if self.openSourceFile(path):
                    changed=True
                    break
            e=self.editors.get(path)
            if changed and e:
                e.colorLine(line,'#0080ff')
                e.cursorPosition=(line-1,1)
                self.currentLine=line
                e.ensureCursorVisible()
            
        
    def saveWatches(self):
        """ Save all watches to settings, for future sessions """
        res=[]
        n=self.watchesTree.topLevelItemCount()-1
        for i in xrange(0,n):
            item=self.watchesTree.topLevelItem(i)
            if len(res)>0:
                res.append(';')
            res.append(item.text(0))
        settings=QtCore.QSettings()
        key='watches:{}'.format(self.debugger.debugged)
        settings.setValue(key,''.join(res))
        
    def loadWatches(self):
        """ Load all previous session watches from settings """
        while self.watchesTree.topLevelItemCount()>1:
            self.watchesTree.takeTopLevelItem(0)
        settings=QtCore.QSettings()
        key='watches:{}'.format(self.debugger.debugged)
        val=settings.value(key,'').toString()
        if len(val)>0:
            arr=val.split(';')
            if len(arr)>0:
                res=[]
                for watch in arr:
                    res.append(QtGui.QTreeWidgetItem([watch]))
                self.watchesTree.insertTopLevelItems(0,res)
        
    def updateLocals(self):
        locals=self.debugger.getLocals()
        self.localsTree.clear()
        for var in locals.keys():
            item=QtGui.QTreeWidgetItem([var])
            self.localsTree.addTopLevelItem(item)
            res=locals.get(var)
            if res:
                self.updateWatchItem(item,res)
        
    def updateWatches(self):
        """ Re-evaluate the value of each watch and update view """
        n=self.watchesTree.topLevelItemCount()-1
        for i in xrange(0,n):
            item=self.watchesTree.topLevelItem(i)
            item.takeChildren()
            expr=item.text(0)
            res=self.debugger.evaluate(expr)
            if res:
                self.updateWatchItem(item,res)

    def updateWatchItem(self,item,root):
        item.setText(1,root.value)
        def addChildren(item,node):
            for c in node.children:
                subitem=QtGui.QTreeWidgetItem([c.name])
                subitem.setText(1,c.value)
                item.addChild(subitem)
                addChildren(subitem,c)
        addChildren(item,root)
                    
    def updateCallstack(self):
        bt=self.debugger.getBackTrace()
        self.stackList.clear()
        for line in bt:
            self.stackList.addItem(line)
    
    def startDebug(self):
        if self.debugger:
            self.actCont()
            return
        self.outputEdit.setPlainText('')
        cmd=[self.workspaceTree.getExecutablePath()]
        args=self.workspaceTree.getDebugParams().split()
        cwd=self.workspaceTree.getDebugDirectory()
        if len(cwd)<1:
            cwd=self.workspaceTree.mainPath()
        for a in args:
            cmd.append(a)
        self.debugger=GDBWrapper(self.breakpoints,cmd,cwd)
        #self.showWatchesPane()
        #self.showCallStackPane()
        #self.loadDebugWindowState()
        self.showDebugPanes()
        self.loadWatches()
        self.timer.start(50)
        qutepart.evaluator=self.debugger.evaluateAsText
        
    def stopDebugger(self):
        if self.debugger:
            qutepart.evaluator=None
            for path in self.editors:
                e=self.editors.get(path)
                e.colorLine(0,'')
            self.saveDebugWindowState()
            self.debugger.quitDebugger()
            self.debugger=None
            #self.paneWatches.close()
            #self.paneWatches=None
            #self.paneStack.close()
            #self.paneStack=None
            self.hideDebugPanes()
            self.timer.stop()
    
    def hideDebugPanes(self):
        self.paneWatches.hide()
        self.paneLocals.hide()
        self.paneStack.hide()

    def showDebugPanes(self):
        self.paneWatches.show()
        self.paneLocals.show()
        self.paneStack.show()

        
    def clearBreakpoints(self):
        self.breakpoints.clear()
        n=self.central.count()
        for i in xrange(0,n):
            self.central.widget(i).bpMarks={}
        if self.debugger:
            self.debugger.clearBreakpoints()

    def actStep(self):
        if self.debugger:
            self.debugger.actStep()
            if not self.debugger.running:
                self.stopDebugger()

    def actNext(self):
        if self.debugger:
            self.debugger.actNext()
            if not self.debugger.running:
                self.stopDebugger()

    def actOut(self):
        if self.debugger:
            self.debugger.actOut()
            if not self.debugger.running:
                self.stopDebugger()

    def actCont(self):
        if self.debugger:
            e=self.getCurrentEditor()
            if e:
                e.colorLine(0,'')
                self.currentLine=-1
            self.debugger.actCont()

    def actBreak(self):
        if self.debugger:
            self.debugger.actBreak()

    def actStop(self):
        if self.debugger:
            self.debugger.actStop()

    
    def update(self):
        """ Called every 50ms to check if a change in debugger state occurred
        
        Basically this is waiting for a change of state, indicated by:
        * self.debugger.changed
        
        If a change is detected, everything is re-evaluated and drawn
        
        """
        if self.debugger:
            self.debugger.update()
            #if len(text)>0:
            #    self.addOutputText(text)
            if self.debugger.hasOutput():
                self.addOutputText(self.debugger.getOutput())
            if self.debugger.changed:
                self.updatePosition()
                self.updateWatches()
                self.updateLocals()
                self.updateCallstack()
                self.debugger.changed=False
            if not self.debugger.running:
                self.stopDebugger()
        # If the debugger is active running the program,
        # create an indication using an animation in the top left
        # corner of the application window
        if self.debugger and self.debugger.active:
            if self.runningWidget is None:
                from running import RunningWidget
                self.runningWidget=RunningWidget(self)
                self.runningWidget.show()
            self.outputEdit.setBlinkingCursor(True)
            s=self.outputEdit.getInput()
            if len(s)>0:
                text=''.join(s)
                self.debugger.sendInput(text)
                self.addOutputText(text)
        else:
            self.outputEdit.clearInput()
            self.outputEdit.setBlinkingCursor(False)
            if not self.runningWidget is None:
                self.runningWidget.close()
                self.runningWidget=None
