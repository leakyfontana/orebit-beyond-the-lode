using UnityEngine;
using System.Collections;
using System.Collections.Generic;
public class AutoDestroy : MonoBehaviour

//This code destroys the particle's GameObject once it's Start Time is over.
//Also, if you're having issues with particles vanishing after you get far from them, just set their XYZ Scale values to 2, 2, 2

{
    private float timeLeft;

	public void Awake()
    {
        ParticleSystem system = GetComponent<ParticleSystem>();
        timeLeft = system.main.startLifetime.constant;
    }
    public void Update()
    {
        timeLeft -= Time.deltaTime;
        if (timeLeft <= 0)
        {
            GameObject.Destroy(gameObject);
        }
    }
}