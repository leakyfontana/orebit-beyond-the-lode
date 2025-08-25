using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

public class EndingScreen : MonoBehaviour
{
	public void returnToMainMenu(){
		Time.timeScale = 1f;
		AudioManager audio = FindObjectOfType<AudioManager>();
		if(audio) {
			audio.StopAllMusic();
			audio.StopAllSounds();			
		}
		SceneManager.LoadScene("MainMenu");
	}
}
