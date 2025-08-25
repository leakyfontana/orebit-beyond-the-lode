using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

public class OptionsUIManager : MonoBehaviour
{
	public GameObject player;
	public GameObject ui_manager;
	public GameObject sound_slider;
	public GameObject music_slider;
    // Start is called before the first frame update
    void Start()
    {
        
    }

	// Update is called once per frame
    void Update()
    {
        if (Input.GetKeyDown(KeyCode.Escape)){
            closeUI();
        }
    }
	
	public void openUI(){
		if(player.activeSelf && !ui_manager.GetComponent<UIManager>().isUIOpen()){
			player.GetComponent<PlayerMovement>().enterShop();
			gameObject.SetActive(true);
			music_slider.GetComponent<Slider>().value = LevelData.music_volume;
			sound_slider.GetComponent<Slider>().value = LevelData.sound_volume;
		}
	}

	public void closeUI(){
		player.GetComponent<PlayerMovement>().exitShop();
		gameObject.SetActive(false);
		PlayerPrefs.SetFloat("music_volume", music_slider.GetComponent<Slider>().value);
		PlayerPrefs.SetFloat("sound_volume", sound_slider.GetComponent<Slider>().value);
		LevelData.setVolumeLevels();
		FindObjectOfType<AudioManager>().setNewVolumeLevels();
	}
}
