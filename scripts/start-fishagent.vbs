' Start FishAgent over HTTPS without leaving a console window on screen.
'
' Placed in the Startup folder, a plain .bat would keep a command prompt open
' for as long as the server runs, which is forever. This wrapper runs the real
' batch file hidden and records its output, so a startup that fails is still
' visible afterwards instead of failing silently.
'
' It also refuses to start a second copy: two processes cannot bind one port,
' and the loser would write a bind error to the log on every login.
'
' NOTE: the repo path contains CJK characters. This file must stay pure ASCII,
' because cscript reads a .vbs in the system ANSI codepage (GBK here) unless it
' is UTF-16 -- a UTF-8 file makes the embedded path unmatchable and the script
' silently decides the batch file is missing.

Option Explicit

Const PORT = "8018"

Dim shell, fso, root, bat, logDir, logFile, candidate, found
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' The log path is fixed and CJK-free, so it is available for early errors.
logDir = "D:\FishAgent\logs"
logFile = logDir & "\uvicorn-" & PORT & ".log"
If Not fso.FolderExists(logDir) Then fso.CreateFolder logDir

' The repo path contains CJK, which cannot be written here (see NOTE above), so
' it is resolved at runtime, in this order:
'
'   1. <script dir>\..            -- works when run from the repo's scripts\.
'   2. D:\FishAgent\repo-root.txt -- the Startup-folder case. A copy in Startup
'      sits two levels under Programs\, nowhere near the repo, so the path has
'      to come from a file. That file is UTF-8 and CJK-capable: the limitation
'      is only that THIS script must stay ASCII.
'   3. %FISHAGENT_ROOT%          -- manual override.
found = ""
candidate = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
If fso.FileExists(candidate & "\serve-https.bat") Then found = candidate

If found = "" Then
  Dim pointer, f, line
  ' Initialise before the guarded Set: comparing an unassigned object variable
  ' with Nothing raises "Object required" in VBScript.
  Set f = Nothing
  pointer = "D:\FishAgent\repo-root.txt"
  If fso.FileExists(pointer) Then
    On Error Resume Next
    Set f = fso.OpenTextFile(pointer, 1, False, -1)  ' -1 = Unicode (UTF-16)
    If Err.Number <> 0 Then
      Err.Clear
      Set f = fso.OpenTextFile(pointer, 1, False, 0)  ' fall back to ANSI
    End If
    On Error GoTo 0
    If Not f Is Nothing Then
      Do While Not f.AtEndOfStream
        line = Trim(f.ReadLine)
        If Len(line) > 0 And Left(line, 1) <> "#" Then
          If fso.FileExists(line & "\serve-https.bat") Then found = line
          Exit Do
        End If
      Loop
      f.Close
    End If
  End If
End If

If found = "" Then
  candidate = shell.ExpandEnvironmentStrings("%FISHAGENT_ROOT%")
  ' ExpandEnvironmentStrings returns the literal text when unset.
  If InStr(candidate, "%") = 0 Then
    If fso.FileExists(candidate & "\serve-https.bat") Then found = candidate
  End If
End If

If found = "" Then
  WriteLine logFile, Now & "  ERROR: serve-https.bat not found. Asked: script parent, " & _
    "D:\FishAgent\repo-root.txt, %FISHAGENT_ROOT%."
  WScript.Quit 1
End If

root = found
bat = root & "\serve-https.bat"
logDir = "D:\FishAgent\logs"
logFile = logDir & "\uvicorn-" & PORT & ".log"

If Not fso.FileExists(bat) Then
  WriteLine logFile, Now & "  ERROR: batch file not found: " & bat
  WScript.Quit 1
End If

' Already listening? Two processes cannot share the port, and the loser would
' log a bind error on every login.
Dim probe
probe = ""
On Error Resume Next
probe = shell.Exec("cmd /c netstat -ano | findstr /C:"":8018"" | findstr /C:""LISTENING""").StdOut.ReadAll
On Error GoTo 0
If Len(Trim(probe)) > 0 Then
  WriteLine logFile, Now & "  skipped: something already listens on " & PORT
  WScript.Quit 0
End If

WriteLine logFile, Now & "  starting " & bat

' "start /b" detaches the server from cscript. Without it, the child is torn
' down when the launcher exits -- which happens immediately, so the server
' started, logged nothing and died before it could bind the port.
'
' The launcher window style stays hidden (2nd arg 0) and it does not wait
' (3rd arg False) so login is not blocked.
Dim rc
rc = shell.Run( _
    "cmd /c start /b """" /min cmd /c """ & bat & """ >> """ & logFile & """ 2>&1", _
    0, False)
WriteLine logFile, Now & "  launcher returned " & rc

Sub WriteLine(path, text)
  Dim f
  On Error Resume Next
  Set f = fso.OpenTextFile(path, 8, True)
  If Err.Number = 0 Then
    f.WriteLine text
    f.Close
  End If
  On Error GoTo 0
End Sub
