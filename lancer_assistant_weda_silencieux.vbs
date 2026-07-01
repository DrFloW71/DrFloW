Option Explicit

Dim fso
Dim shell
Dim scriptDir
Dim command

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
command = """" & scriptDir & "\lancer_assistant_weda.cmd" & """ --silent"

shell.Run command, 0, False
