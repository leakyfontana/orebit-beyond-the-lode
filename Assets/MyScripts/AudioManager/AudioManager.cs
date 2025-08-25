using UnityEngine.Audio;
using System;
using UnityEngine;
using System.Collections.Generic;

public class AudioManager : MonoBehaviour
{

	public static AudioManager instance;

	public AudioMixerGroup mixerGroup;

	public Sound[] sounds;
	public Sound[] musics;
	
	private List<Sound> paused_sounds;

	void Awake()
	{
		if (instance != null)
		{
			Destroy(gameObject);
		}
		else
		{
			instance = this;
			DontDestroyOnLoad(gameObject);
		}

		foreach (Sound s in sounds)
		{
			s.source = gameObject.AddComponent<AudioSource>();
			s.source.clip = s.clip;
			s.source.loop = s.loop;

			s.source.outputAudioMixerGroup = mixerGroup;
		}
		
		foreach (Sound m in musics)
		{
			m.source = gameObject.AddComponent<AudioSource>();
			m.source.clip = m.clip;
			m.source.loop = m.loop;

			m.source.outputAudioMixerGroup = mixerGroup;
		}
	}
	
	public void PlayMusic(string sound){ //This will stop all other music playing
		StopAllMusic();
		Sound m = Array.Find(musics, item => item.name == sound);
		if (m == null)
		{
			Debug.LogWarning("Sound: " + name + " not found!");
			return;
		}
		m.source.volume = m.volume * (1f + UnityEngine.Random.Range(-m.volumeVariance / 2f, m.volumeVariance / 2f)) * LevelData.music_volume;
		m.source.pitch = m.pitch * (1f + UnityEngine.Random.Range(-m.pitchVariance / 2f, m.pitchVariance / 2f));

		m.source.Play();
	}
	
	public void StopMusic(string sound)
	{
		Sound m = Array.Find(musics, item => item.name == sound);
		m.source.Stop();
	}
	
	public void StopAllMusic(){
		foreach (Sound m_to_stop in musics){
			m_to_stop.source.Stop();
		}
	}

	public void PlaySound(string sound)
	{
		Sound s = Array.Find(sounds, item => item.name == sound);
		if (s == null)
		{
			Debug.LogWarning("Sound: " + name + " not found!");
			return;
		}
		s.source.volume = s.volume * (1f + UnityEngine.Random.Range(-s.volumeVariance / 2f, s.volumeVariance / 2f)) * LevelData.sound_volume;
		s.source.pitch = s.pitch * (1f + UnityEngine.Random.Range(-s.pitchVariance / 2f, s.pitchVariance / 2f));

		s.source.Play();
	}
	
	public void StopSound(string sound)
	{
		Sound s = Array.Find(sounds, item => item.name == sound);
		s.source.Stop();
	}
	
	public void PlaySoundOneShot(string sound){
		Sound s = Array.Find(sounds, item => item.name == sound);
		if (s == null)
		{
			Debug.LogWarning("Sound: " + name + " not found!");
			return;
		}
		s.source.volume = s.volume * (1f + UnityEngine.Random.Range(-s.volumeVariance / 2f, s.volumeVariance / 2f)) * LevelData.sound_volume;
		s.source.pitch = s.pitch * (1f + UnityEngine.Random.Range(-s.pitchVariance / 2f, s.pitchVariance / 2f));

		s.source.PlayOneShot(s.clip);
	}
	
	public void ChangeSoundPitch(string sound, float value_to_add){
		Sound s = Array.Find(sounds, item => item.name == sound);
		if (s == null)
		{
			Debug.LogWarning("Sound: " + name + " not found!");
			return;
		}
		s.source.pitch = s.pitch + value_to_add;
	}

	public void ChangeSoundVolume(string sound, float value_to_add){
		Sound s = Array.Find(sounds, item => item.name == sound);
		if (s == null)
		{
			Debug.LogWarning("Sound: " + name + " not found!");
			return;
		}
		s.source.volume = s.volume + value_to_add;
	}

	public void ChangeMusicPitch(string sound, float value_to_add){
		Sound m = Array.Find(sounds, item => item.name == sound);
		if (m == null)
		{
			Debug.LogWarning("Sound: " + name + " not found!");
			return;
		}
		m.source.pitch = m.pitch + value_to_add;
	}

	public void ChangeMusicVolume(string sound, float value_to_add){
		Sound m = Array.Find(sounds, item => item.name == sound);
		if (m == null)
		{
			Debug.LogWarning("Sound: " + name + " not found!");
			return;
		}
		m.source.volume = m.volume + value_to_add;
	}
	
	public void setNewVolumeLevels(){
		foreach (Sound m in musics){
			m.source.volume = m.volume * (1f + UnityEngine.Random.Range(-m.volumeVariance / 2f, m.volumeVariance / 2f)) * LevelData.music_volume;
		}
		foreach (Sound s in sounds){
			s.source.volume = s.volume * (1f + UnityEngine.Random.Range(-s.volumeVariance / 2f, s.volumeVariance / 2f)) * LevelData.sound_volume;
		}
	}
	
	public void PauseSounds(){
		paused_sounds = new List<Sound>();
		foreach (Sound s in sounds){
			if(s.source.isPlaying){
				s.source.Pause();
				paused_sounds.Add(s);
			}
		}
	}
	
	public void StopAllSounds(){
		foreach (Sound s in sounds){
			if(s.source.isPlaying){
				s.source.Stop();
			}
		}
	}
	
	public void ResumeSounds(){
		foreach (Sound s in paused_sounds){
			s.source.UnPause();
		}
	}
}
