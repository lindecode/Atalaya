param(
    [ValidateSet('activar', 'desactivar', 'estado')][string]$Accion = 'estado',
    [ValidateRange(1, 1440)][int]$Minutos = 5
)
. "$PSScriptRoot\comun.ps1"

$TaskName = 'Atalaya - ciclo automatico'

switch ($Accion) {
    'activar' {
        $python = Get-Python
        $action = New-ScheduledTaskAction -Execute $python -Argument 'main.py cycle' -WorkingDirectory $Root
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
            -RepetitionInterval (New-TimeSpan -Minutes $Minutos)
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Minutes ([Math]::Max(10, $Minutos)))
        $principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
            -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
            -Principal $principal -Description 'Recoleccion incremental y analisis condicionado de Atalaya' -Force | Out-Null
        Write-Ok "Ciclo automatico activado cada $Minutos minuto(s). Solo se ejecuta mientras el usuario tenga sesion."
    }
    'desactivar' {
        if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Ok 'Ciclo automatico eliminado'
        } else { Write-Ok 'No estaba configurado' }
    }
    'estado' {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $task) { Write-Host '  Ciclo automatico: desactivado'; exit 0 }
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Ok "Estado: $($task.State); ultima: $($info.LastRunTime); proxima: $($info.NextRunTime); codigo: $($info.LastTaskResult)"
    }
}
