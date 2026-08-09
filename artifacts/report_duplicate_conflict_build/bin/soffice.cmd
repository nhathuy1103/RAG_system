@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0word_soffice_shim.ps1" %*
