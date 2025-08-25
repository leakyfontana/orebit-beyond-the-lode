using UnityEngine.Audio;
using UnityEngine;

[System.Serializable]
public class Sound {

	public string name;

	public AudioClip clip;

	public float volume = .75f;
	public float volumeVariance = .1f;

	public float pitch = 1f;
	public float pitchVariance = .1f;

	public bool loop = false;

	public AudioMixerGroup mixerGroup;

	[HideInInspector]
	public AudioSource source;

}
