using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class ExplosionWithoutParticlesBehavior : MonoBehaviour
{
	public ParticleSystem emit;
    // Start is called before the first frame update
    void Start(){
        GetComponent<Animator>().SetInteger("ExplosionNumber", Random.Range(1, 4));
    }

    // Update is called once per frame
    void Update()
    {
        
    }
	
	public void destroy(){
        //This destroys the projectile
        Destroy (gameObject);
	}
}
