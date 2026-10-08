param([string]$Storyboard, [string]$OutputDir)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$videoSpeech = New-Object System.Speech.Synthesis.SpeechSynthesizer
$videoChineseVoices = @($videoSpeech.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'zh-CN' })
if ($videoChineseVoices.Count -eq 0) { throw 'No Chinese SAPI voice installed' }
$videoChosenVoice = $videoChineseVoices | Where-Object { $_.VoiceInfo.Name -eq 'Microsoft Kangkang' } | Select-Object -First 1
if (-not $videoChosenVoice) { $videoChosenVoice = $videoChineseVoices[0] }
$videoSpeech.SelectVoice($videoChosenVoice.VoiceInfo.Name)
$videoSpeech.Rate = 0
$videoSpeech.Volume = 100
$videoScript = Get-Content -LiteralPath $Storyboard -Raw -Encoding UTF8 | ConvertFrom-Json
try {
    foreach ($videoScene in $videoScript.scenes) {
        $videoAudioTarget = Join-Path $OutputDir ($videoScene.scene_id + '_sapi.wav')
        $videoSpeech.SetOutputToWaveFile($videoAudioTarget)
        $videoSpeech.Speak($videoScene.subtitle_text)
        $videoSpeech.SetOutputToNull()
        Write-Output ('[VOICE] ' + $videoScene.scene_id + ' SAPI generated')
    }
} finally {
    $videoSpeech.Dispose()
}
