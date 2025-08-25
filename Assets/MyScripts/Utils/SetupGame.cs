using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class SetupGame : MonoBehaviour
{
	private AudioManager audio_manager;
    // Start is called before the first frame update
    void Start()
    {
		Application.targetFrameRate = 60;
		audio_manager = FindObjectOfType<AudioManager>();
		audio_manager.PlayMusic("MainLevelMusic");
    }

    // Update is called once per frame
    void Update()
    {
        
    }
}
